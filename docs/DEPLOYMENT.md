# DeskPilot Deployment & Operation Guide

[![AWS Bedrock](https://img.shields.io/badge/AWS-Amazon_Bedrock-FF9900?logo=amazon-aws&logoColor=white)](https://aws.amazon.com/bedrock/)
[![Docker](https://img.shields.io/badge/Container-Docker-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)
[![Windows](https://img.shields.io/badge/OS-Windows_10%2B-0078D7?logo=windows&logoColor=white)](https://microsoft.com/windows)

This guide provides step-by-step instructions for deploying and running **DeskPilot** across five distinct environments: Local Desktop, Web Browser Mode, Docker Containers, Standalone Windows Executable (.exe), and Cloud Hosting on AWS.

---

## 📋 Prerequisites & AWS Credentials

### 1. Amazon Bedrock Access
DeskPilot requires access to **Amazon Bedrock**. The default model is **Amazon Nova Pro** (`amazon.nova-pro-v1:0`).

Configure credentials using either of the following methods:

#### Method A: Direct Bedrock API Key (Quickstart)
1. Open the [AWS Bedrock Console](https://console.aws.amazon.com/bedrock/).
2. Generate an API Key.
3. In your `.env` file, set:
   ```env
   BEDROCK_API_KEY=your_bedrock_api_key_here
   BEDROCK_MODEL_ID=amazon.nova-pro-v1:0
   ```

#### Method B: AWS IAM Access Keys (Production / Enterprise)
1. Create an IAM User or Role with the following policy:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Action": [
           "bedrock:InvokeModel",
           "bedrock:InvokeModelWithResponseStream"
         ],
         "Resource": "*"
       }
     ]
   }
   ```
2. In your `.env` file, set:
   ```env
   AWS_ACCESS_KEY_ID=your_access_key_here
   AWS_SECRET_ACCESS_KEY=your_secret_key_here
   AWS_DEFAULT_REGION=us-east-1
   BEDROCK_MODEL_ID=amazon.nova-pro-v1:0
   ```

---

## 🚀 Deployment Methods

![DeskPilot Desktop Running Interface](../assets/screenshots/dashboard.png)

### Method 1: Local Desktop App (Windows Native)
Runs DeskPilot in a native Microsoft Edge WebView2 desktop window with system integration.

```bash
# 1. Clone repository
git clone https://github.com/your-repo/deskpilot.git
cd deskpilot

# 2. Create and activate virtual environment
python -m venv venv
venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up environment
cp .env.example .env
# Edit .env with your AWS credentials

# 5. Launch desktop application
python main.py
```

---

### Method 2: Local Web Browser Mode
Runs DeskPilot as a local web application accessible via Chrome, Edge, or Firefox at `http://localhost:5000`.

![DeskPilot Conversational Web Interface](../assets/screenshots/chat_interface.png)

```bash
python main.py --web
```
*Or run directly:*
```bash
python backend/server.py --open
```

---

### Method 3: Docker & Docker Compose (Container Deployment)
Deploys DeskPilot as a self-contained container with persistent volumes for deliverables and chat history.

![DeskPilot Containerized Organization Run](../assets/screenshots/desktop_organization.png)

#### Using Docker Compose (Recommended)
```bash
# 1. Ensure .env is populated with your AWS credentials
cp .env.example .env

# 2. Build and launch the container
docker compose up -d

# 3. View logs
docker compose logs -f

# 4. Open in browser
# Navigate to http://localhost:5000
```

#### Using Standalone Docker CLI
```bash
# Build the image
docker build -t deskpilot:latest .

# Run container with volume mounts
docker run -d \
  --name deskpilot \
  -p 5000:5000 \
  --env-file .env \
  -v $(pwd)/output:/app/output \
  -v $(pwd)/chats:/app/chats \
  deskpilot:latest
```

---

### Method 4: Standalone Windows Executable (`.exe`)
Build a standalone executable that packages Python, all tools, assets, and frontend files into a portable binary that runs without requiring Python to be installed.

#### 1. Build Executable with PyInstaller
Run the provided automated build script:
```bat
scripts\build.bat
```
*Or via PowerShell:*
```powershell
.\scripts\build.ps1
```

The compiled standalone executable will be located at:
```
dist\DeskPilot\DeskPilot.exe
```

#### 2. Package into Windows Installer (.exe Setup Wizard)
If [Inno Setup 6](https://jrsoftware.org/isdl.php) is installed on your machine:
```bat
iscc installer\deskpilot_setup.iss
```
This generates a production installer `DeskPilot-Setup-v2.0.0.exe` in `dist\installer\`.

---

### Method 5: AWS Cloud Deployment

#### Option A: AWS App Runner (Serverless Web App)
1. Push your Docker image to **Amazon Elastic Container Registry (ECR)**:
   ```bash
   aws ecr create-repository --repository-name deskpilot
   aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com
   docker tag deskpilot:latest <ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/deskpilot:latest
   docker push <ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/deskpilot:latest
   ```
2. Open the **AWS App Runner Console** -> **Create Service**.
3. Select your ECR image `<ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/deskpilot:latest`.
4. Under **Instance role**, assign an IAM role with `bedrock:InvokeModel*` permissions.
5. Set Port to `5000`.
6. Deploy! App Runner provides an automated HTTPS URL with autoscaling.

#### Option B: AWS ECS Fargate
1. Define a Task Definition pointing to the ECR image with `PORT=5000` and Task Execution Role with Bedrock permissions.
2. Launch an ECS Service under AWS Fargate with an Application Load Balancer.

#### Option C: Amazon EC2
1. Launch an Amazon Linux 2023 or Ubuntu EC2 instance with an IAM Instance Profile granting Bedrock access.
2. Install Docker:
   ```bash
   sudo yum install -y docker
   sudo systemctl enable --now docker
   ```
3. Run the DeskPilot container:
   ```bash
   docker run -d -p 80:5000 -e HOST=0.0.0.0 -e PORT=5000 deskpilot:latest
   ```

---

## 🔍 Healthcheck & Diagnostic Endpoints

DeskPilot includes built-in REST endpoints for container orchestrators and monitoring:

| Endpoint | Method | Purpose | Sample Response |
|---|---|---|---|
| `/api/status` | `GET` | System health & agent counts | `{"status": "ready", "version": "2.0.0", "model_id": "amazon.nova-pro-v1:0"}` |
| `/api/agents` | `GET` | List all active agents | `[{"id": "personal_assistant", "status": "active", ...}]` |
| `/api/events` | `GET` | SSE stream for real-time tokens | Server-Sent Events stream |
