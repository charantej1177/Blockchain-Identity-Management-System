import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'super-secret-key-123'
    MYSQL_HOST = 'localhost'
    MYSQL_USER = 'root'
    MYSQL_PASSWORD = ''
    MYSQL_DB = 'blockchain_identity'
    MYSQL_CURSORCLASS = 'DictCursor'
    
    # Blockchain settings
    WEB3_PROVIDER_URI = 'http://127.0.0.1:7545'
    CONTRACT_ADDRESS = os.environ.get('CONTRACT_ADDRESS')
