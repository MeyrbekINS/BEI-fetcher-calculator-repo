# --- START OF FILE Calculate_Breakeven.py ---
import boto3
import pandas as pd
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
import os
import math # For isfinite check

# --- Configuration from Environment Variables ---
# This tag will determine which datasets to fetch (e.g., "1D", "5D", "1Y", "5Y")
TIME_RANGE_TAG = os.environ.get('TIME_RANGE_TAG', '1D')

# Metric ID components
METRIC_ID_PREFIX_SOURCE = os.environ.get('METRIC_ID_PREFIX_SOURCE', 'CNBC')
METRIC_NAME_SUFFIX_SOURCE = os.environ.get('METRIC_NAME_SUFFIX_SOURCE', 'Close')

NOMINAL_YIELD_SYMBOL = os.environ.get('NOMINAL_YIELD_SYMBOL', 'US10Y')
REAL_YIELD_SYMBOL = os.environ.get('REAL_YIELD_SYMBOL', 'US10YTIP')

METRIC_ID_PREFIX_OUTPUT = os.environ.get('METRIC_ID_PREFIX_OUTPUT', 'CALCULATED')
OUTPUT_METRIC_NAME = os.environ.get('OUTPUT_METRIC_NAME', 'Breakeven_Inflation')
METRIC_NAME_SUFFIX_OUTPUT = os.environ.get('METRIC_NAME_SUFFIX_OUTPUT', 'Rate')
UNIT_FOR_OUTPUT_METRIC = os.environ.get('UNIT_FOR_OUTPUT_METRIC', '%')


# Construct the source and output Metric IDs
NOMINAL_METRIC_ID = f"{METRIC_ID_PREFIX_SOURCE}_{NOMINAL_YIELD_SYMBOL}_{TIME_RANGE_TAG}_{METRIC_NAME_SUFFIX_SOURCE}"
REAL_METRIC_ID = f"{METRIC_ID_PREFIX_SOURCE}_{REAL_YIELD_SYMBOL}_{TIME_RANGE_TAG}_{METRIC_NAME_SUFFIX_SOURCE}"
BREAKEVEN_METRIC_ID = f"{METRIC_ID_PREFIX_OUTPUT}_{OUTPUT_METRIC_NAME}_{TIME_RANGE_TAG}_{METRIC_NAME_SUFFIX_OUTPUT}"

# --- DynamoDB Setup ---
DYNAMODB_TABLE_NAME = os.environ.get('DYNAMODB_TABLE', 'RealTimeChartData')
try:
    dynamodb = boto3.resource('dynamodb') # Assumes region is configured via Fargate task role or AWS_REGION env var
    table = dynamodb.Table(DYNAMODB_TABLE_NAME)
except Exception as e:
    print(f"Error initializing DynamoDB resource: {e}")
    raise

def query_metric_data(metric_id):
    """Queries all data for a given metricId from DynamoDB and returns a DataFrame."""
    print(f"Querying DynamoDB for metricId: {metric_id}")
    items = []
    try:
        response = table.query(
            KeyConditionExpression=boto3.dynamodb.conditions.Key('metricId').eq(metric_id)
            # Add ScanIndexForward=False and Limit if you only want the latest, but for calculation we need a good range
        )
        items.extend(response.get('Items', []))
        while 'LastEvaluatedKey' in response:
            response = table.query(
                KeyConditionExpression=boto3.dynamodb.conditions.Key('metricId').eq(metric_id),
                ExclusiveStartKey=response['LastEvaluatedKey']
            )
            items.extend(response.get('Items', []))
        
        if not items:
            print(f"No items found for metricId: {metric_id}")
            return pd.DataFrame(columns=['DateTime', 'Value'])

        # Convert to DataFrame
        df = pd.DataFrame(items)
        if 'timestamp' not in df.columns or 'value' not in df.columns:
            print(f"Queried data for {metric_id} is missing 'timestamp' or 'value' columns.")
            return pd.DataFrame(columns=['DateTime', 'Value'])
            
        df['DateTime'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        # Convert Decimal from DynamoDB to float for calculation
        df['Value'] = df['value'].apply(lambda x: float(x) if isinstance(x, Decimal) else x) 
        print(f"Successfully fetched {len(df)} items for {metric_id}.")
        return df[['DateTime', 'Value']]

    except Exception as e:
        print(f"Error querying DynamoDB for {metric_id}: {e}")
        return pd.DataFrame(columns=['DateTime', 'Value']) # Return empty DataFrame on error


def store_calculated_data_in_dynamodb(df, metric_id_to_store, unit):
    """Processes the calculated DataFrame and stores each data point in DynamoDB."""
    # This function is very similar to the one in CNBC_Fetcher.py
    # Re-implementing or importing might be options in a larger project.
    if df is None or df.empty:
        print(f"Calculated DataFrame for {metric_id_to_store} is None or empty, nothing to store.")
        return 0

    items_stored_count = 0
    if table is None:
        print("DynamoDB table object is not initialized. Cannot store data.")
        return 0

    with table.batch_writer() as batch:
        for index, row in df.iterrows(): # df should have 'DateTime' and 'Value'
            datetime_obj = row['DateTime'] # Already a UTC datetime object
            db_timestamp = int(datetime_obj.timestamp() * 1000)
            
            current_value = row['Value']

            if pd.isna(current_value): # Check for NaN
                print(f"Skipping row due to NaN value for {metric_id_to_store} at {datetime_obj}")
                continue
            
            try:
                # Ensure value is finite before converting to Decimal
                if not isinstance(current_value, (int, float, Decimal)):
                    temp_value = float(current_value) # If it was a string representation
                else:
                    temp_value = current_value

                if not math.isfinite(temp_value):
                    print(f"Skipping row due to non-finite value (Infinity): {temp_value} for {metric_id_to_store} at {datetime_obj}")
                    continue
                
                value_for_db = Decimal(str(current_value)) # Convert original value to Decimal
            except (ValueError, TypeError, InvalidOperation) as e:
                print(f"Could not convert value '{current_value}' to Decimal for {metric_id_to_store} at {datetime_obj}. Error: {e}")
                continue

            source_date_str = datetime_obj.strftime('%Y-%m-%d %H:%M:%S %Z') # Include timezone

            item = {
                'metricId': metric_id_to_store,
                'timestamp': db_timestamp,
                'value': value_for_db,
                'sourceDate': source_date_str, # This represents the common timestamp of the source data
                'unit': unit
            }
            batch.put_item(Item=item)
            items_stored_count += 1
            
    print(f"Successfully prepared {items_stored_count} items for metric '{metric_id_to_store}' for DynamoDB batch write.")
    return items_stored_count

if __name__ == "__main__":
    print(f"--- Running Breakeven Inflation Rate Calculator ---")
    print(f"Time Range Tag: {TIME_RANGE_TAG}")
    print(f"Fetching Nominal Yield ({NOMINAL_METRIC_ID})...")
    df_nominal = query_metric_data(NOMINAL_METRIC_ID)

    print(f"\nFetching Real Yield ({REAL_METRIC_ID})...")
    df_real = query_metric_data(REAL_METRIC_ID)

    if df_nominal.empty or df_real.empty:
        print("One or both source datasets are empty. Cannot calculate breakeven rate.")
        print(f"Nominal data points: {len(df_nominal)}, Real data points: {len(df_real)}")
    else:
        print(f"\nAligning data by DateTime (timestamps)...")
        # Merge on DateTime. Using an inner merge ensures we only calculate where both data points exist.
        df_merged = pd.merge(df_nominal, df_real, on='DateTime', suffixes=('_nominal', '_real'), how='inner')

        if df_merged.empty:
            print("No common timestamps found between nominal and real yield datasets. Cannot calculate.")
        else:
            print(f"Found {len(df_merged)} common data points for calculation.")
            # Calculate Breakeven Inflation Rate
            df_merged['Value'] = df_merged['Value_nominal'] - df_merged['Value_real']
            
            df_breakeven = df_merged[['DateTime', 'Value']].copy()
            # Round to a reasonable number of decimal places if desired, e.g., 4
            # df_breakeven['Value'] = df_breakeven['Value'].round(4) 

            print(f"\nStoring calculated {BREAKEVEN_METRIC_ID} data into DynamoDB...")
            items_written = store_calculated_data_in_dynamodb(df_breakeven, BREAKEVEN_METRIC_ID, UNIT_FOR_OUTPUT_METRIC)
            print(f"DynamoDB storage process completed. {items_written} items for {BREAKEVEN_METRIC_ID} processed.")

    print(f"--- Breakeven Inflation Rate Calculator Finished ---")

# --- END OF FILE Calculate_Breakeven.py ---