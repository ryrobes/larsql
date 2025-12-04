#!/bin/bash

# Set variables (customize these)
IMAGE_NAME="ubuntu-ssh"
CONTAINER_NAME="ubuntu-container"
HOST_PORT=2222
ROOT_PASSWORD="your_secure_password"  # CHANGE THIS!

# Packages to install automatically (add more as needed, space-separated)
APT_PACKAGES="python3 python3-pip nodejs ruby golang-go git curl clojure"  # Example: langs and tools
PIP_PACKAGES="numpy pandas requests"  # Example Python deps; add more if needed

# Check and destroy existing container if it exists
if docker ps -a --format '{{.Names}}' | grep -q "^$CONTAINER_NAME$"; then
    echo "Existing container '$CONTAINER_NAME' found. Stopping and removing..."
    docker stop $CONTAINER_NAME >/dev/null 2>&1
    docker rm -f $CONTAINER_NAME >/dev/null 2>&1
    echo "Existing container removed."
fi

# Check and remove existing image if it exists (to force rebuild)
if docker images -q $IMAGE_NAME > /dev/null; then
    echo "Existing image '$IMAGE_NAME' found. Removing to force rebuild..."
    docker rmi $IMAGE_NAME >/dev/null 2>&1
    echo "Existing image removed."
fi

# Define Dockerfile content via heredoc (with automatic installs)
DOCKERFILE_CONTENT=$(cat <<EOF
FROM ubuntu:latest

RUN apt-get update && \\
    apt-get install -y openssh-server $APT_PACKAGES && \\
    mkdir /var/run/sshd && \\
    echo 'root:$ROOT_PASSWORD' | chpasswd && \\
    sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin yes/' /etc/ssh/sshd_config && \\
    sed 's@session\\s*required\\s*pam_loginuid.so@session optional pam_loginuid.so@g' -i /etc/pam.d/sshd

# Install Python packages if any
RUN if [ -n "$PIP_PACKAGES" ]; then pip3 install --break-system-packages $PIP_PACKAGES; fi

EXPOSE 22

CMD ["/usr/sbin/sshd", "-D"]
EOF
)

# Build the image by piping the heredoc to docker build
echo "$DOCKERFILE_CONTENT" | docker build -t $IMAGE_NAME -f - . || { echo "Build failed! Exiting."; exit 1; }

# Run the container
docker run -d --name $CONTAINER_NAME -p $HOST_PORT:22 $IMAGE_NAME

# Output instructions
echo "Container started! SSH in with: ssh root@localhost -p $HOST_PORT"
echo "Password: $ROOT_PASSWORD (change it inside the container for security)"
echo "Note: The image includes preinstalled packages: $APT_PACKAGES and pip: $PIP_PACKAGES"
echo "Rerun this script to rebuild if messed up (it will force rebuild)."