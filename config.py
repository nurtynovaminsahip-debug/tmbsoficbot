import os

BOT_TOKEN = os.environ.get('BOT_TOKEN', '')
ADMIN_GROUP_ID = int(os.environ.get('ADMIN_GROUP_ID', '0'))
OWNER_ID = int(os.environ.get('OWNER_ID', '0'))
CHANNEL_USERNAME = os.environ.get('CHANNEL_USERNAME', '@TrasnferMarktBrawlStars')

COOLDOWN = 30
LOG_PAGE_SIZE = 10
