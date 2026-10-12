import os
import boto3

client = boto3.client("athena")

def handler(event, context):
    response = client.get_named_query(
        NamedQueryId=os.environ['ATHENA_QUERY_ID']
    )
    query_string = response["NamedQuery"]["QueryString"]
    client.start_query_execution(
        QueryString=query_string,
        QueryExecutionContext={
            'Database': 'default',
        },
        ResultConfiguration={
            'OutputLocation': 's3://%s/results/' % (os.environ['LOGS_BUCKET'])
        },
        WorkGroup='primary',
    )
