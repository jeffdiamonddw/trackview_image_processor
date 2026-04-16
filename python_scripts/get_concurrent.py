import boto3
from datetime import datetime, timedelta

def get_current_concurrency(function_name):
    """
    Retrieves the most recent Maximum ConcurrentExecutions metric 
    from CloudWatch for a specific Lambda function.
    """
    cloudwatch = boto3.client('cloudwatch')
    
    # Define time range: looking at the last 10 minutes to ensure we find a datapoint
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(minutes=10)
    
    try:
        response = cloudwatch.get_metric_statistics(
            Namespace='AWS/Lambda',
            MetricName='ConcurrentExecutions',
            Dimensions=[
                {'Name': 'FunctionName', 'Value': function_name}
            ],
            StartTime=start_time,
            EndTime=end_time,
            Period=60,  # 1-minute granularity
            Statistics=['Maximum']
        )
        
        datapoints = response.get('Datapoints', [])
        
        if not datapoints:
            print(f"No execution data found for {function_name} in the last 10 minutes.")
            return 0
            
        # Sort by timestamp to find the most recent datapoint
        latest_datapoint = sorted(datapoints, key=lambda x: x['Timestamp'])[-1]
        return latest_datapoint['Maximum']
        
    except Exception as e:
        return f"Error: {str(e)}"

if __name__ == "__main__":
    target_function = "process-image-handler"
    count = get_current_concurrency(target_function)
    
    print(f"--- Lambda Monitoring ---")
    print(f"Function: {target_function}")
    print(f"Current Concurrent Executions (Peak in last minute): {count}")