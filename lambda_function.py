import json
import boto3
import os
from datetime import datetime, timedelta, timezone
import decimal

# Helper class to convert a DynamoDB item to JSON.
class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, decimal.Decimal):
            if o % 1 > 0: # Check if it has a fractional part
                return float(o)
            else:
                return int(o)
        return super(DecimalEncoder, self).default(o)

# --- Key Change Here ---
# Specify the region where your DynamoDB table resides
DYNAMODB_REGION = 'eu-north-1' 
dynamodb = boto3.resource('dynamodb', region_name=DYNAMODB_REGION) # Pass region_name
# --- End of Key Change ---

table_name = os.environ.get('DYNAMODB_TABLE', 'RealTimeChartData')
table = dynamodb.Table(table_name)

def lambda_handler(event, context):
    print(f"Received event: {event}")
    print(f"Interacting with DynamoDB table '{table_name}' in region '{DYNAMODB_REGION}'") # Added log for region

    query_params = event.get('queryStringParameters', {})
    metric_ids_str = query_params.get('metricId', 'SOFR_Overnight')
    metric_ids_to_query = [metric_id.strip() for metric_id in metric_ids_str.split(',')]

    try:
        days_to_fetch = int(query_params.get('days', 30))
        if days_to_fetch <= 0 or days_to_fetch > 365:
            days_to_fetch = 30
    except ValueError:
        days_to_fetch = 30

    today_utc_midnight = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    start_date_utc = today_utc_midnight - timedelta(days=days_to_fetch)
    start_timestamp_ms = int(start_date_utc.timestamp() * 1000)
    
    print(f"Fetching data for metrics: {metric_ids_to_query}, last {days_to_fetch} days from {start_date_utc.isoformat()}")

    all_results = {}

    for metric_id in metric_ids_to_query:
        try:
            # Ensure your Partition Key name is exactly 'metricId' in the us-east-1 table
            print(f"Querying for metricId: '{metric_id}'")
            response = table.query(
                KeyConditionExpression=boto3.dynamodb.conditions.Key('metricId').eq(metric_id) & boto3.dynamodb.conditions.Key('timestamp').gte(start_timestamp_ms),
                ScanIndexForward=True
            )
            all_results[metric_id] = response.get('Items', [])

        except Exception as e:
            print(f"Error querying DynamoDB for metric {metric_id}: {e}")
            return {
                'statusCode': 500,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({'error': f"Error querying DynamoDB for metric {metric_id}: {str(e)}"})
            }

    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': json.dumps(all_results, cls=DecimalEncoder)
    }
