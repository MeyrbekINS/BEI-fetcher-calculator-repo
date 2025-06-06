# --- START OF FILE Dockerfile_Breakeven --- (Name it differently or use a different build context)
# Use an official Python runtime from Amazon ECR Public Gallery
FROM public.ecr.aws/docker/library/python:3.9-slim-buster

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
# (Ensure pandas and boto3 are in this requirements.txt)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the script into the container
COPY CNBC-BEI.py .

# Make Python output unbuffered
ENV PYTHONUNBUFFERED 1

# Command to run the application
CMD ["python", "CNBC-BEI.py"]
# --- END OF FILE Dockerfile_Breakeven ---
