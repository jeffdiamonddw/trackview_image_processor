import boto3
import json
import re

def s3_list_files(session, s3_path):
    """
    list files in an S3 bucket

    
    """

    m = re.match("s3://(?P<bucket>[^/]+)(|/)(?P<path>.*)", s3_path)
   
    bucket = m.group('bucket')
    path =   m.group('path').lstrip('/')
    
    
    s3_client = session.client('s3')
    objects = s3_client.list_objects_v2(Bucket=bucket, Prefix = path)
    if 'Contents' not in objects:
        return []
    key_list = [x['Key'] for x in objects['Contents']]

    return ["s3://{}/{}".format(bucket, key) for key in key_list] 


bucket_name = "ts-wkbch-file-uploads-bkt-fbef377"
flight_id = "DEMO__20260227__cando_north_2__d6d81a20"


image_folder = "s3://{}/{}".format(bucket_name, flight_id)
image_paths = [filename for filename in s3_list_files(boto3, image_folder) if filename.lower().endswith('.jpg')]

event_template = open('templates/s3_lambda_call_template.json').read()
client = boto3.client("lambda")

for image_path in image_paths:
    print('running {}'.format(image_path))
    object_name = "{}/{}".format(flight_id, image_path.split('/')[-1])
    event = json.loads(event_template.replace('bucket_name', bucket_name).replace('object_name', object_name))

    response = client.invoke(
            FunctionName='process-image-handler',
            InvocationType="Event",  # Asynchronous invocation
            Payload=bytes(json.dumps(event), encoding='utf-8')
        )
    
 


