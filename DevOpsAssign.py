import boto3
import requests
import random
import string
import os
import json
import logging
import subprocess
from botocore.exceptions import ClientError

# Configure the logging settings
logging.basicConfig(
    filename='devops_ass1.log',  # Log to a file
    level=logging.INFO,           # Log only INFO level and above
    format='%(asctime)s - %(levelname)s - %(message)s'  # Log format
)

# AWS S3 resource for object operations and EC2 resource
s3 = boto3.resource('s3')  # This is needed for s3.Object method
ec2 = boto3.resource('ec2')
s3client = boto3.client('s3')
ec2client = boto3.client('ec2')  # Needed to use waiters

def monitoring_script(public_dns,key_file_path):
    script_path = 'monitoring.sh'
    
    # Log SCP script upload
    logging.info(f"Starting to upload {script_path} to {public_dns} via SCP.")
    
    # SCP command to copy the monitoring script to EC2 instance
    scp_script_command = f"scp -o StrictHostKeyChecking=no -i \"{key_file_path}\" {script_path} ec2-user@{public_dns}:."
    scp_script_result = subprocess.run(scp_script_command, shell=True, capture_output=True, text=True)
    
    if scp_script_result.returncode == 0:
        logging.info(f"Successfully uploaded {script_path} to {public_dns}.")
    else:
        logging.error(f"Failed to upload {script_path} to {public_dns}. Error: {scp_script_result.stderr}")
    
    # Log chmod command execution
    logging.info(f"Setting execute permissions on {public_dns} for {script_path}.")
    
    # SSH command to chmod the script
    ssh_chmod_command = f"ssh -o StrictHostKeyChecking=no -i \"{key_file_path}\" ec2-user@{public_dns} 'chmod 700 {script_path}'"
    chmod_result = subprocess.run(ssh_chmod_command, shell=True, capture_output=True, text=True)
    
    if chmod_result.returncode == 0:
        logging.info(f"Successfully set permissions for {script_path} on {public_dns}.")
    else:
        logging.error(f"Failed to set permissions for {script_path} on {public_dns}. Error: {chmod_result.stderr}")
    
    # Log execution of the script
    logging.info(f"Executing {script_path} on {public_dns}.")
    
    # SSH command to execute the script on EC2
    ssh_execute_command = f"ssh -o StrictHostKeyChecking=no -i \"{key_file_path}\" ec2-user@{public_dns} './{script_path}'"
    execute_result = subprocess.run(ssh_execute_command, shell=True, capture_output=True, text=True)
    
    if execute_result.returncode == 0:
        logging.info(f"Successfully executed {script_path} on {public_dns}. Output: {execute_result.stdout}")
    else:
        logging.error(f"Failed to execute {script_path} on {public_dns}. Error: {execute_result.stderr}")

# Function to generate 6 character strings at random
def generate_bucket_name(name):
    random_chars = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"{random_chars}-{name}"

# Function to create the S3 bucket
def create_s3_bucket(bucket_name, region='us-east-1'):
    try:
        s3.create_bucket(Bucket=bucket_name)
        logging.info(f"Bucket {bucket_name} created successfully.")
    except ClientError as e:
        logging.error(f"Error creating bucket: {e}")
        raise

# Function to download the image
def download_image(url, file_name):
    try:
        logging.info(f"Starting image download from {url}")
        response = requests.get(url)
        
        # Check if the request was successful
        if response.status_code == 200:
            with open(file_name, 'wb') as f:
                f.write(response.content)
            logging.info(f"Image {file_name} downloaded successfully.")
        else:
            logging.warning(f"Failed to download image from {url}. HTTP Status: {response.status_code}")
    except requests.RequestException as e:
        logging.error(f"Error occurred while downloading image from {url}: {e}")
        raise

# Function to disable public access block for the S3 bucket
def disable_public_access_block(bucket_name):
    s3client.delete_public_access_block(Bucket=bucket_name)
    logging.info(f"Public access block disabled for {bucket_name}.")

# Function to set a public read policy on the bucket
def set_bucket_policy(bucket_name):
    bucket_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "PublicReadGetObject",
                "Effect": "Allow",
                "Principal": "*",
                "Action": ["s3:GetObject"],
                "Resource": f"arn:aws:s3:::{bucket_name}/*"
            }
        ]
    }
    
    s3client.put_bucket_policy(Bucket=bucket_name, Policy=json.dumps(bucket_policy))
    logging.info(f"Public read policy set for {bucket_name}.")

# Function to upload file to S3
def upload_to_s3(bucket_name, file_name, key):
    try:
        logging.info(f"Uploading {file_name} to S3 bucket {bucket_name} as {key}.")
        
        with open(file_name, 'rb') as file_data:
            s3.Object(bucket_name, key).put(
                Body=file_data,
                ContentType='text/html'  # Adjust ContentType based on file type
            )
        
        logging.info(f"Successfully uploaded {file_name} to {bucket_name} as {key}.")
    
    except FileNotFoundError:
        logging.error(f"File {file_name} not found. Please check the file path.")
    
    except ClientError as e:
        logging.error(f"Failed to upload {file_name} to S3 bucket {bucket_name}: {e}")
    
    except Exception as e:
        logging.error(f"An unexpected error occurred during upload: {e}")
        raise

# Function to enable static website hosting for the S3 bucket
def configure_static_website(bucket_name):
    website_configuration = {
        'IndexDocument': {'Suffix': 'index.html'}
    }
    s3client.put_bucket_website(Bucket=bucket_name, WebsiteConfiguration=website_configuration)
    logging.info(f"Static website hosting enabled for {bucket_name}.")

# Function to set up EC2 instance with metadata display
def create_ec2_instance():
    user_data = """#!/bin/bash
    yum update -y
    yum install httpd -y
    systemctl start httpd
    systemctl enable httpd
    
    # Fetch session token for IMDSv2
    TOKEN=$(curl -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
    
    # Fetch instance metadata using the session token
    INSTANCE_ID=$(curl -H "X-aws-ec2-metadata-token: $TOKEN" -s http://169.254.169.254/latest/meta-data/instance-id)
    PRIVATE_IP=$(curl -H "X-aws-ec2-metadata-token: $TOKEN" -s http://169.254.169.254/latest/meta-data/local-ipv4)
    INSTANCE_TYPE=$(curl -H "X-aws-ec2-metadata-token: $TOKEN" -s http://169.254.169.254/latest/meta-data/instance-type)
    AVAILABILITY_ZONE=$(curl -H "X-aws-ec2-metadata-token: $TOKEN" -s http://169.254.169.254/latest/meta-data/placement/availability-zone)
    
    # Create the web page displaying metadata
    echo "<html>
    <head>
    <title>Instance Metadata</title>
    </head>
    <body>
    <h1>Welcome to the EC2 Instance Metadata Page</h1>
    <p><strong>Instance ID:</strong> $INSTANCE_ID</p>
    <p><strong>Private IP:</strong> $PRIVATE_IP</p>
    <p><strong>Instance Type:</strong> $INSTANCE_TYPE</p>
    <p><strong>Availability Zone:</strong> $AVAILABILITY_ZONE</p>
    </body>
    </html>" > /var/www/html/index.html
    
    systemctl restart httpd
    """
    try:
        new_instances = ec2.create_instances(
            ImageId='ami-0fff1b9a61dec8a5f',
            MinCount=1,
            MaxCount=1,
            InstanceType='t2.nano',
            KeyName='demo2',
            SecurityGroupIds=['sg-0188c1b98bfa62839'],
            UserData=user_data,
            TagSpecifications=[
                {
                    'ResourceType': 'instance',
                    'Tags': [{'Key': 'Name', 'Value': 'MMaryAssign'}]
                }
            ]
        )
        instance_id = new_instances[0].id
        logging.info(f"EC2 Instance created with ID: {instance_id}")
    except ClientError as e:
        logging.error(f"Error creating EC2 instance: {e}")
        raise
    
    # Wait for the instance to be running
    waiter = ec2client.get_waiter('instance_running')
    waiter.wait(InstanceIds=[instance_id])
    
    # Fetch the public DNS once the instance is running
    instance_info = ec2client.describe_instances(InstanceIds=[instance_id])
    public_dns = instance_info['Reservations'][0]['Instances'][0]['PublicDnsName']
    
    logging.info(f"EC2 instance is running. Public DNS: {public_dns}")
    key_file_path = "/home/matteo/Downloads/demo2.pem"
    monitoring_script(public_dns, key_file_path)

    return public_dns

# Main script
if __name__ == "__main__":
    my_name = "matteomary"
    bucket_name = generate_bucket_name(my_name)

    # Create S3 bucket and set its configuration
    create_s3_bucket(bucket_name)
    disable_public_access_block(bucket_name)
    set_bucket_policy(bucket_name)

    # Download image and upload files
    image_url = "http://devops.witdemo.net/logo.jpg"
    image_file = "logo.jpg"
    download_image(image_url, image_file)

    # Create index.html
    index_file = "index.html"
    try:
        with open(index_file, 'w') as f:
            f.write(f"<html><body><img src='https://{bucket_name}.s3.amazonaws.com/{image_file}'/></body></html>")
        logging.info(f"{index_file} created successfully.")
    except Exception as e:
        logging.error(f"Error creating {index_file}: {e}")

    # Upload files to S3 and configure website
    upload_to_s3(bucket_name, image_file, image_file)
    upload_to_s3(bucket_name, index_file, index_file)
    configure_static_website(bucket_name)

    # Output the S3 website URL
    s3_website_url = f"http://{bucket_name}.s3-website-us-east-1.amazonaws.com"
    logging.info(f"S3 Website URL: {s3_website_url}")

    # Create EC2 instance and fetch its public DNS
    ec2_public_dns = create_ec2_instance()

    # Write URLs to matteomary-websites.txt
    file_name = f"matteomary-websites-{bucket_name}.txt"
try:
    with open(file_name, 'w') as f:
        f.write(f"S3 Website URL: {s3_website_url}\n")
        f.write(f"EC2 Metadata URL: http://{ec2_public_dns}/index.html\n")
    logging.info(f"URLs written to {file_name} successfully.")
except Exception as e:
    logging.error(f"Error writing URLs to {file_name}: {e}")
    
