from supabase import create_client
from dotenv import load_dotenv
import os

load_dotenv()
sb = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY'))

def save_reel(user_id, url):
    result = sb.table('reels').insert({
        'user_id': user_id,
        'url': url,
        'status': 'processing'
    }).execute()
    return result.data[0]['id']

def update_reel(reel_id, data):
    sb.table('reels').update(data).eq('id', reel_id).execute()

def get_user_reels(user_id):
    result = sb.table('reels')\
        .select('*')\
        .eq('user_id', user_id)\
        .eq('status', 'done')\
        .order('created_at', desc=True)\
        .execute()
    return result.data
