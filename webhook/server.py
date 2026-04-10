#!/usr/bin/env python3
"""
GitHub Webhook Listener for Auto-Deploy

Listens for push events from GitHub and triggers deploy.sh

Run with: python server.py
Or as Docker container alongside other services.

GitHub Webhook setup:
1. Go to repo Settings → Webhooks → Add webhook
2. Payload URL: https://your-argo-domain.com/webhook
3. Content type: application/json
4. Secret: your-webhook-secret (set in .env)
5. Events: Just the push event
"""

import os
import hmac
import hashlib
import subprocess
import logging
from flask import Flask, request, jsonify

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
WEBHOOK_SECRET = os.environ.get('WEBHOOK_SECRET', '')
DEPLOY_SCRIPT = os.environ.get('DEPLOY_SCRIPT', '/app/deploy-local.sh')
ALLOWED_BRANCHES = ['main', 'master']


def verify_signature(payload: bytes, signature: str) -> bool:
    """Verify GitHub webhook signature"""
    if not WEBHOOK_SECRET:
        logger.warning("WEBHOOK_SECRET not set, skipping verification")
        return True
    
    if not signature:
        return False
    
    expected = 'sha256=' + hmac.new(
        WEBHOOK_SECRET.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(expected, signature)


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok'})


@app.route('/webhook', methods=['POST'])
def webhook():
    """GitHub webhook endpoint"""
    # Verify signature
    signature = request.headers.get('X-Hub-Signature-256', '')
    if not verify_signature(request.data, signature):
        logger.warning("Invalid webhook signature")
        return jsonify({'error': 'Invalid signature'}), 401
    
    # Parse event
    event = request.headers.get('X-GitHub-Event', '')
    payload = request.json
    
    if event != 'push':
        logger.info(f"Ignoring event: {event}")
        return jsonify({'status': 'ignored', 'event': event})
    
    # Check branch
    ref = payload.get('ref', '')
    branch = ref.replace('refs/heads/', '')
    
    if branch not in ALLOWED_BRANCHES:
        logger.info(f"Ignoring push to branch: {branch}")
        return jsonify({'status': 'ignored', 'branch': branch})
    
    # Get commit info
    commits = payload.get('commits', [])
    pusher = payload.get('pusher', {}).get('name', 'unknown')
    
    logger.info(f"Received push to {branch} by {pusher} ({len(commits)} commits)")
    
    # Trigger deploy
    try:
        result = subprocess.run(
            [DEPLOY_SCRIPT],
            capture_output=True,
            text=True,
            timeout=300  # 5 min timeout
        )
        
        if result.returncode == 0:
            logger.info("Deploy successful")
            return jsonify({
                'status': 'deployed',
                'branch': branch,
                'commits': len(commits)
            })
        else:
            logger.error(f"Deploy failed: {result.stderr}")
            return jsonify({
                'status': 'failed',
                'error': result.stderr
            }), 500
            
    except subprocess.TimeoutExpired:
        logger.error("Deploy timed out")
        return jsonify({'status': 'timeout'}), 500
    except Exception as e:
        logger.error(f"Deploy error: {e}")
        return jsonify({'status': 'error', 'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 9000))
    logger.info(f"Starting webhook server on port {port}")
    app.run(host='0.0.0.0', port=port)
