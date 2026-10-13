import boto3
from databricks import sql

def handler(event, context):
    print(event)
