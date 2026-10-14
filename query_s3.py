import os
import json
import boto3
import pandas as pd
from pprint import pprint

from databricks import sql

s3 = boto3.client("s3")

def handler(event, context):
    pprint(event)

    databricks_token = os.environ['DATABRICKS_TOKEN']
    databricks_host =  os.environ['DATABRICKS_HOST']
    front_end_bucket =  os.environ['FRONT_END_S3']
    
    query_bucket = event["detail"]["bucket"]["name"]
    query_file = event["detail"]["object"]["key"]

    #1. load new log data to databricks
    saved_query = s3.get_object(Bucket=query_bucket, Key=query_file)["Body"]
    logs_table = pd.read_csv(saved_query)

    conn = sql.connect(server_hostname=databricks_host,
                   http_path="/sql/1.0/warehouses/47594432480270a0",
                   access_token=databricks_token,
        )
    cursor = conn.cursor()
    check_command = "select count(*) last_rows from ironpond.default.cloudfront_logs where date = ?"

    cursor.execute(check_command,list(logs_table.date.unique()))
    last_rows = cursor.fetchone()["last_rows"]
    
    #b. insert if no rows exist for that date
    if last_rows == 0:
        insert_ddl= 'insert into \
            ironpond.default.cloudfront_logs (date,time,location,request_ip,referrer,method,host,uri,status,user_agent,xforwarded_for) values\n'
        rows = []

        for n, log in logs_table.iterrows():
            insert_row = '("{date}","{time}","{location}","{request_ip}","{referrer}","{method}","{host}","{uri}",{status},"{user_agent}","{xforwarded_for}")'.format(**log)
            rows.append(insert_row)

        insert_ddl = insert_ddl + ",\n".join(rows)
        cursor.execute(insert_ddl)

        #2. create aggregates
        #a. website uri with visit count
        select_top_uris = 'select uri,count(uri) visitors from ironpond.default.cloudfront_logs where uri in \
            ("/","/resume","/portfolio","/about","metrics") group by uri order by visitors desc;'
        cursor.execute(select_top_uris)
        data = cursor.fetchall()
        top_uris = pd.DataFrame(data,columns=["uri","visits"])
        
        #b. month with visit count
        select_visits_per_month = 'select date(date_trunc("month",timestamp(date))) month,count(time) visits \
            from ironpond.default.cloudfront_logs where date is not null and uri in ("/","/resume","/portfolio","/about","metrics") \
            group by month order by month desc;'
        cursor.execute(select_visits_per_month)
        data = cursor.fetchall()
        monthly_visits = pd.DataFrame(data,columns=["month","visits"])
        monthly_visits.month = monthly_visits.month.astype(str)

        #c. edgepoint location visit count
        select_location_visits = 'select substring(location,0,3) country_iso,count(time) visits from ironpond.default.cloudfront_logs  \
            where location is not null and uri in ("/","/resume","/portfolio","/about","metrics") group by country_iso order by visits desc;'
        cursor.execute(select_location_visits)
        data =  pd.DataFrame(cursor.fetchall(),columns=["country_iso","visits"])

        edge_points = pd.read_json("edge_iata_iso.json",orient="index").reset_index()
        location_visits = pd.merge(data, edge_points, how="left",left_on="country_iso",right_on="index")[["country","visits"]]\
            .groupby("country")\
            .aggregate({"visits":"sum"})\
            .sort_values("visits").reset_index()
        
        highcharts_data = json.dumps({"locations":location_visits.to_dict(orient="records"),
                        "months":monthly_visits.to_dict(orient="records"),
                        "uris":top_uris.to_dict(orient="records")})
        
        s3.put_object(Bucket=front_end_bucket, Body=highcharts_data,
                        Key="app_data/visits.json", ACL="public-read")
