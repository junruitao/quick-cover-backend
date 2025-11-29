# Use the official lightweight Python image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY app.py .

# Define the port the container will listen on
ENV PORT 8080

# Run the application using Uvicorn, listening on 0.0.0.0 and the defined port
CMD exec uvicorn app:app --host 0.0.0.0 --port $PORT