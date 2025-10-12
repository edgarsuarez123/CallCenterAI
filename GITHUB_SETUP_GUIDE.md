# GitHub Repository Setup Guide

## ⚠️ CRITICAL SECURITY WARNINGS

**BEFORE PUSHING TO GITHUB, YOU MUST:**

1. **Remove all sensitive files** (see list below)
2. **Set up proper .gitignore** (already created)
3. **Use environment variables** for all secrets
4. **Verify no secrets are in code**

## Files to Remove Before Pushing

### 1. Sensitive Configuration Files
```bash
# Remove these files (they contain secrets):
rm gateway/google_credentials.json
rm .env  # if it exists
rm *.env  # any environment files
```

### 2. Database Data Directory
```bash
# Remove the entire data directory (contains database files):
rm -rf data/
```

### 3. Python Cache Files
```bash
# Remove Python cache files:
find . -name "__pycache__" -type d -exec rm -rf {} +
find . -name "*.pyc" -delete
```

## Safe Files to Keep

✅ **These files are safe to commit:**
- All source code files (.py, .html, .yaml, .md)
- Configuration templates (env.example)
- Documentation files
- Docker files
- Requirements files
- Test files (optional)

## Step-by-Step GitHub Setup

### 1. Clean the Repository
```bash
# Remove sensitive files
rm gateway/google_credentials.json
rm -rf data/
rm -rf gateway/__pycache__/
rm -rf gateway/models/__pycache__/
rm -rf gateway/routes/__pycache__/
rm -rf gateway/services/__pycache__/
find . -name "*.pyc" -delete

# Verify sensitive files are gone
ls -la gateway/google_credentials.json  # Should show "No such file"
ls -la data/  # Should show "No such file"
```

### 2. Initialize Git Repository
```bash
# Initialize git (if not already done)
git init

# Add all files (respecting .gitignore)
git add .

# Check what will be committed
git status

# Verify no sensitive files are staged
git diff --cached --name-only | grep -E "(google_credentials|\.env|data/)"
# Should return nothing
```

### 3. Create Initial Commit
```bash
# Create initial commit
git commit -m "Initial commit: CallCenterAI HIPAA-compliant healthcare communication system

- Multi-tenant architecture with clinic isolation
- Natural language processing for conversational AI
- Google Calendar integration with OAuth
- HIPAA-compliant PHI tokenization
- Comprehensive API and web interface
- Docker containerization and deployment ready"
```

### 4. Create GitHub Repository
1. Go to GitHub.com
2. Click "New repository"
3. **IMPORTANT**: Select "Private" repository
4. Name it: `CallCenterAI` or `callcenter-ai`
5. **DO NOT** initialize with README (you already have files)
6. Click "Create repository"

### 5. Push to GitHub
```bash
# Add remote origin
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git

# Push to GitHub
git push -u origin main
```

## Post-Push Security Checklist

### 1. Verify Repository Contents
- [ ] No `google_credentials.json` file
- [ ] No `data/` directory
- [ ] No `.env` files
- [ ] No `__pycache__` directories
- [ ] All source code is present
- [ ] Documentation files are present

### 2. Set Up Environment Variables
Create a secure way to manage environment variables:

**Option A: Local .env file (for development)**
```bash
# Create .env file locally (DO NOT commit)
cp env.example .env
# Edit .env with your actual values
```

**Option B: GitHub Secrets (for CI/CD)**
1. Go to repository Settings → Secrets and variables → Actions
2. Add these secrets:
   - `DATABASE_URL`
   - `CLINIC_TOKEN_HMAC_KEY_BASE64`
   - `AES_GCM_KEY_BASE64`
   - `GOOGLE_CLIENT_ID`
   - `GOOGLE_CLIENT_SECRET`

**Option C: Cloud Provider Secrets (for production)**
- AWS Secrets Manager
- Azure Key Vault
- Google Secret Manager
- HashiCorp Vault

### 3. Update Documentation
- [ ] Update README.md with setup instructions
- [ ] Include environment variable setup guide
- [ ] Add Google Calendar setup instructions
- [ ] Include deployment guide

## Repository Structure After Push

```
CallCenterAI/
├── .gitignore                 # Git ignore rules
├── .github/                   # GitHub workflows (optional)
├── SECURITY.md               # Security policy
├── DEPLOYMENT_GUIDE.md       # Deployment instructions
├── env.example               # Environment variables template
├── CALL_CENTER_AI_TECHNICAL_SPECIFICATION.md
├── CALL_CENTER_AI_ENGINEERING_DOCUMENTATION.md
├── compose/                  # Docker compose files
│   ├── gateway.yaml
│   └── orchestrator.yaml
├── gateway/                  # Main application
│   ├── main.py
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── models/              # Database models
│   ├── routes/              # API routes
│   ├── services/            # Business logic
│   └── templates/           # Web templates
├── orchestrator/            # Orchestration service
└── README.md               # Project documentation
```

## Security Best Practices

### 1. Repository Access
- [ ] Keep repository private
- [ ] Limit access to authorized personnel only
- [ ] Use branch protection rules
- [ ] Require pull request reviews

### 2. Code Security
- [ ] Regular dependency updates
- [ ] Security scanning in CI/CD
- [ ] Code review for all changes
- [ ] No hardcoded secrets in code

### 3. Deployment Security
- [ ] Use secure environment variable management
- [ ] Implement proper access controls
- [ ] Regular security audits
- [ ] Monitor for security vulnerabilities

## Troubleshooting

### If You Accidentally Commit Secrets

1. **Immediately rotate the secrets** (change passwords, regenerate keys)
2. **Remove from git history**:
   ```bash
   git filter-branch --force --index-filter \
   'git rm --cached --ignore-unmatch gateway/google_credentials.json' \
   --prune-empty --tag-name-filter cat -- --all
   ```
3. **Force push** (if repository is private):
   ```bash
   git push origin --force --all
   ```

### If Repository Becomes Public

1. **Immediately make it private**
2. **Rotate all secrets**
3. **Check GitHub's security advisory**
4. **Review access logs**

## Next Steps

After successfully pushing to GitHub:

1. **Set up CI/CD pipeline** (GitHub Actions)
2. **Configure automated testing**
3. **Set up deployment automation**
4. **Implement monitoring and alerting**
5. **Create backup and disaster recovery procedures**

## Support

If you encounter issues:
1. Check the SECURITY.md file
2. Review the DEPLOYMENT_GUIDE.md
3. Verify all sensitive files are removed
4. Ensure environment variables are properly configured
