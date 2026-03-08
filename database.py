from supabase import create_client
from dotenv import load_dotenv
import os

load_dotenv()
sb = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY'))

def save_reminder(user_id, message, remind_at):
    sb.table('reminders').insert({
        'user_id': user_id,
        'message': message,
        'remind_at': remind_at,
        'sent': False
    }).execute()

def get_due_reminders():
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    result = sb.table('reminders')\
        .select('*')\
        .eq('sent', False)\
        .lte('remind_at', now)\
        .execute()
    return result.data

def mark_reminder_sent(reminder_id):
    sb.table('reminders')\
        .update({'sent': True})\
        .eq('id', reminder_id)\
        .execute()

def get_user_reminders(user_id):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    result = sb.table('reminders')\
        .select('*')\
        .eq('user_id', user_id)\
        .eq('sent', False)\
        .gte('remind_at', now)\
        .order('remind_at')\
        .execute()
    return result.data
