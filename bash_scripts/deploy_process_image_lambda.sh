aws ecr get-login-password --region ca-central-1 | sudo docker login --username AWS --password-stdin 786487085471.dkr.ecr.ca-central-1.amazonaws.com
docker build -f docker/process_image.dockerfile --platform linux/amd64 -t process-image-handler .
docker tag process-image-handler 786487085471.dkr.ecr.ca-central-1.amazonaws.com/process-image-handler:process-image-handler
sudo docker push 786487085471.dkr.ecr.ca-central-1.amazonaws.com/process-image-handler:process-image-handler

aws lambda delete-function --function-name process-image-handler

aws lambda create-function \
  --function-name process-image-handler \
  --package-type Image \
  --code ImageUri=786487085471.dkr.ecr.ca-central-1.amazonaws.com/process-image-handler:process-image-handler \
  --role arn:aws:iam::786487085471:role/tile-server \
  --timeout 900 \
  --memory-size 10240 \
  --ephemeral-storage Size=10240 \
  --region ca-central-1


#python3 python_scripts/refresh_sns_subscription.py trackview-process-image process-image-handler
