ARG FUNCTION_DIR="/function"


FROM osgeo_gdal_1

# Include global arg in this stage of the build
ARG FUNCTION_DIR

ENV AWS_DEFAULT_REGION="ca-central-1"
ENV AWS_SECRET_ACCESS_KEY="m6xMuF6aS1ICxek/GNDILO1MI91L9WJm4TkZKAdE"
ENV AWS_ACCESS_KEY_ID="AAKIA3OHSIRGP3CUF4GUK"

COPY python_scripts/trackview_image_processor.py ${FUNCTION_DIR}




# Set working directory to function root directory
WORKDIR ${FUNCTION_DIR}

#For deployment to lambda
ENTRYPOINT [ "/usr/bin/python3", "-m", "awslambdaric" ]
CMD ["trackview_image_processor.lambda_handler" ]