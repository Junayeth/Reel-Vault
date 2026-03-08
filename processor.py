import google.generativeai as genai
import yt_dlp, tempfile, json, os
from database import update_reel
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
model = genai.GenerativeModel("gemini-1.5-flash")

def process_reel(reel_id, url):
    with tempfile.TemporaryDirectory() as tmpdir:
        ydl_opts = {
            'format': 'mp4',
            'outtmpl': f'{tmpdir}/video.mp4',
            'quiet': True
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                caption = info.get('description', '')
        except Exception:
            update_reel(reel_id, {'status': 'url_only'})
            return {
                'title': 'Reel saved',
                'summary': 'Could not process automatically. Add notes manually.',
                'tags': []
            }

        video_file = genai.upload_file(f'{tmpdir}/video.mp4', mime_type="video/mp4")

        response = model.generate_content([
            video_file,
            f"""Instagram caption: {caption}

Watch this video and return ONLY a JSON object, no markdown, no backticks:
{{
  "transcript": "all spoken words in the video",
  "visual_description": "what is shown on screen",
  "title": "short descriptive title",
  "summary": "2 sentence summary combining audio and visuals",
  "tags": ["tag1", "tag2", "tag3"],
  "category": "Food|Travel|Fitness|Fashion|Comedy|Education|Other"
}}"""
        ])

        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            text = response.text
            start, end = text.find('{'), text.rfind('}') + 1
            data = json.loads(text[start:end])

        update_reel(reel_id, {'status': 'done', 'caption': caption, **data})
        return data


def answer_question(question, reels):
    context = "\n\n".join([
        f"Reel {i+1} — {r['title']}:\n"
        f"Summary: {r['summary']}\n"
        f"Transcript: {r.get('transcript', '')[:500]}\n"
        f"Visuals: {r.get('visual_description', '')[:300]}"
        for i, r in enumerate(reels)
    ])

    response = model.generate_content(
        f"Here are the user's saved reels:\n\n{context}\n\n"
        f"Question: {question}\n\n"
        f"Answer based on the reel content. Reference the reel title when relevant."
    )
    return response.text
