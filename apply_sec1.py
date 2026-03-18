import os
import re

# 1A: .gitignore
with open('.gitignore', 'w') as f:
    f.write("""# Python
__pycache__/
*.pyc
*.py[cod]
*$py.class
*.so
.env
logs/
logs/*.log
db.sqlite3
.DS_Store

# Environments
env/
venv/
""")

# 1B: .env
if os.path.exists('.env'):
    lines = open('.env').read().split('\n')
    lines = [L for L in lines if 'ORS_API_KEY' not in L]
    with open('.env', 'w') as f:
        f.write('\n'.join(lines))

# 1C: .env.example
with open('.env.example', 'w') as f:
    f.write("""# Copy this file to .env and fill in your actual values.
# Never commit the real .env file to version control.
SECRET_KEY=your-secret-key-here
DB_NAME=route_tracker_db
DB_USER=your-db-username
DB_PASSWORD=your-db-password
GOOGLE_MAPS_API_KEY=your-google-maps-api-key-here
""")

# 1D: config/settings.py
with open('config/settings.py', 'r') as f:
    settings = f.read()

settings = re.sub(
    r"DATABASES = \{.*?\}",
    """DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('DB_NAME'),
        'USER': config('DB_USER'),
        'PASSWORD': config('DB_PASSWORD'),
        'HOST': 'localhost',
        'PORT': '5432',
    }
}""",
    settings,
    flags=re.DOTALL
)

settings = re.sub(r'ORS_API_KEY.*?\n', '', settings)

settings = re.sub(
    r"CSRF_TRUSTED_ORIGINS = \[.*?\]",
    """CSRF_TRUSTED_ORIGINS = [
    'http://localhost:8000',
    'https://*.ngrok-free.app',
    'https://*.ngrok.io',
]""",
    settings,
    flags=re.DOTALL
)

if 'CSRF_COOKIE_HTTPONLY = False' not in settings:
    settings += '\nCSRF_COOKIE_HTTPONLY = False\n'

with open('config/settings.py', 'w') as f:
    f.write(settings)

# 1E: requirements.txt
with open('requirements.txt', 'w') as f:
    f.write("""Django>=5.0
psycopg2-binary
requests
python-decouple
django-ratelimit
""")

os.makedirs('logs', exist_ok=True)
open('logs/.gitkeep', 'w').close()
print("Section 1 applied.")
