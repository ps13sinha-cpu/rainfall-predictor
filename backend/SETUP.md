# RIIS — Production Setup Guide

## Step-by-Step: Set Up Every External Account

---

## 1. Twilio (SMS + WhatsApp)

**Cost:** ~$1/mo for a phone number + $0.0079/SMS in US. Free trial gives $15 credit.

### Create Account
1. Go to **https://www.twilio.com/try-twilio**
2. Sign up with your email
3. Verify your phone number
4. Choose "SMS" as your primary use case

### Get Credentials
1. Go to **https://console.twilio.com**
2. On the Dashboard, you'll see:
   - **Account SID** — starts with `AC` (e.g., `AC1234567890abcdef`)
   - **Auth Token** — click "Show" to reveal it
3. Copy both values

### Buy a Phone Number
1. Go to **Phone Numbers → Buy a Number**
2. Search for a number in your country (India: +91)
3. Make sure it supports **SMS** and **WhatsApp**
4. Click "Buy" (~$1/mo)
5. Copy the number (e.g., `+919876543210`)

### Enable WhatsApp
1. Go to **Messaging → WhatsApp Sandbox**
2. Follow the instructions to join the sandbox (send a WhatsApp message to the Twilio number)
3. Or apply for a production WhatsApp Business account

### Save to `.env`
```bash
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token_here
TWILIO_FROM_NUMBER=+919876543210
```

---

## 2. Firebase Cloud Messaging (Push Notifications)

**Cost:** Free tier — 50K notifications/day, unlimited device registrations.

### Create Project
1. Go to **https://console.firebase.google.com**
2. Click "Create a project"
3. Name: `riis-alerts` (or anything)
4. Disable Google Analytics (optional)
5. Click "Create project"

### Enable Cloud Messaging
1. In project settings (gear icon → Project Settings)
2. Go to **Cloud Messaging** tab
3. Ensure **Firebase Cloud Messaging API (V1)** is enabled

### Get Service Account Key
1. Go to **Project Settings → Service Accounts**
2. Click "Generate new private key"
3. Download the JSON file
4. Save it as `backend/service-account.json`

### Web Push (for browser notifications)
1. Go to **Project Settings → Cloud Messaging**
2. Scroll to "Web push certificates"
3. Click "Generate key pair"
4. Copy the public key — you'll add it to the frontend

### Save to `.env`
```bash
FIREBASE_CREDENTIALS_PATH=./service-account.json
FCM_SENDER_ID=123456789
FCM_VAPID_KEY=your_web_push_public_key
```

---

## 3. PostgreSQL Database

**Cost:** AWS RDS free tier (12 months): db.t3.micro, 20GB SSD.

### Option A: AWS RDS (Recommended)
1. Go to **https://console.aws.amazon.com/rds**
2. Click "Create database"
3. Choose: **Standard Create → PostgreSQL**
4. Settings:
   - DB instance identifier: `riis-db`
   - Master username: `riis_admin`
   - Master password: (generate a strong one)
5. Instance: **db.t3.micro** (free tier)
6. Storage: **20 GB** (free tier)
7. Connectivity:
   - VPC: default
   - Public access: **Yes**
   - Security group: Create new → allow TCP 5432 from your IP
8. Database options:
   - Initial database name: `riis`
9. Click "Create database" (takes ~5 min)
10. Once available, the endpoint looks like: `riis-db.xxxxx.ap-south-1.rds.amazonaws.com`

### Option B: GCP Cloud SQL
1. Go to **https://console.cloud.google.com/sql**
2. Click "Create Instance → PostgreSQL"
3. Instance ID: `riis-db`
4. Set password
5. Connections: Public IP → Add your IP
6. Create database: `riis`

### Option C: Azure Database for PostgreSQL
1. Go to **https://portal.azure.com**
2. Create "Azure Database for PostgreSQL flexible server"
3. Choose Burstable B1ms (cheapest)
4. Set admin password
5. Create database `riis`

### Save to `.env`
```bash
DATABASE_URL=postgresql+asyncpg://riis_admin:your_password@riis-db.xxxxx.ap-south-1.rds.amazonaws.com:5432/riis
```

---

## 4. Cloud VM for Backend (AWS EC2)

**Cost:** AWS EC2 free tier — t2.micro, 1 year.

### Launch EC2 Instance
1. Go to **https://console.aws.amazon.com/ec2**
2. Click "Launch Instance"
3. Name: `riis-backend`
4. AMI: **Ubuntu 22.04 LTS**
5. Instance: **t2.micro** (free tier)
6. Key pair: Create new → download `.pem` file
7. Network settings:
   - Allow SSH (port 22) from your IP
   - Allow HTTP (port 80) from anywhere
   - Allow custom TCP (port 8000) from anywhere
8. Storage: **20 GB**
9. Click "Launch Instance"

### Connect & Deploy
```bash
# SSH into your instance
ssh -i riis-key.pem ubuntu@<PUBLIC_IP>

# Install Docker
sudo apt update && sudo apt install -y docker.io docker-compose
sudo usermod -aG docker $USER
# Log out and back in

# Clone your project (push to GitHub first, or use scp)
git clone https://github.com/yourusername/riis.git
cd riis

# Create .env file with all your credentials
nano .env

# Start everything
docker-compose up -d
```

### Point Domain (Optional)
1. Buy a domain (e.g., `riis.in` on Route53/GoDaddy)
2. Create an A record pointing to your EC2 public IP
3. Use Let's Encrypt for free HTTPS

---

## 5. `.env` Template (Complete)

Copy this to `backend/.env` and fill in your real values:

```bash
# ── Database ─────────────────────────────────────────────────────────────────
DATABASE_URL=postgresql+asyncpg://riis_admin:YOUR_DB_PASSWORD@YOUR_RDS_ENDPOINT:5432/riis

# ── JWT Auth ─────────────────────────────────────────────────────────────────
SECRET_KEY=generate-a-random-64-char-string-here

# ── Twilio (SMS + WhatsApp) ──────────────────────────────────────────────────
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token_here
TWILIO_FROM_NUMBER=+919876543210

# ── Firebase (Push Notifications) ────────────────────────────────────────────
FIREBASE_CREDENTIALS_PATH=./service-account.json
FCM_SENDER_ID=123456789
FCM_VAPID_KEY=your_web_push_public_key

# ── Server ───────────────────────────────────────────────────────────────────
HOST=0.0.0.0
PORT=8000
```

### Generate a Random Secret Key
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

---

## After Setup — What Happens

| Feature | Simulation Mode | With Real Accounts |
|---------|----------------|-------------------|
| SMS Alerts | Logs message to console | Sends real SMS via Twilio |
| WhatsApp | Logs message | Sends real WhatsApp via Twilio |
| Push Notifications | Logs payload | Sends real push via FCM |
| Database | SQLite (local file) | PostgreSQL (scalable, persistent) |
| ML Model | Formula fallback | XGBoost trained on real historical data |
| File Uploads | Local disk | Can be upgraded to S3 |

### Test Real Integrations

```bash
# Subscribe a real phone number
curl -X POST http://localhost:8000/api/subscriptions/phone \
  -H "Content-Type: application/json" \
  -d '{"phone": "+919876543210", "name": "Test User"}'

# Create and broadcast a real alert
curl -X POST http://localhost:8000/api/alerts/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -d '{"severity": "high", "title": "Test Alert", "body": "This is a test", "area": "Chennai"}'

curl -X POST http://localhost:8000/api/alerts/1/broadcast \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -d '{"channels": ["sms", "push"]}'
```
