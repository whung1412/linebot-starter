import os
import json
import datetime
import traceback
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from google import genai
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

app = Flask(__name__)

LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
SPREADSHEET_ID = os.environ.get('SPREADSHEET_ID')
GOOGLE_CREDENTIALS = os.environ.get('GOOGLE_CREDENTIALS')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
client = genai.Client(api_key=GEMINI_API_KEY)

def get_sheets_service():
    try:
        creds_info = json.loads(GOOGLE_CREDENTIALS)
        creds = Credentials.from_service_account_info(
            creds_info,
            scopes=['https://www.googleapis.com/auth/spreadsheets']
        )
        service = build('sheets', 'v4', credentials=creds)
        return service
    except Exception as e:
        print(f'Sheets 連線錯誤: {e}')
        traceback.print_exc()
        return None

def log_to_sheets(user_id, user_msg, bot_reply):
    try:
        service = get_sheets_service()
        if not service:
            return
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        values = [[now, user_id, user_msg, bot_reply]]
        service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range='工作表1!A:D',
            valueInputOption='RAW',
            body={'values': values}
        ).execute()
        print(f'記錄成功: {now}')
    except Exception as e:
        print(f'記錄失敗: {e}')
        traceback.print_exc()

def get_recent_history(user_id, limit=5):
    try:
        service = get_sheets_service()
        if not service:
            return ""

        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range='工作表1!A:D'
        ).execute()

        rows = result.get('values', [])

        history = []

        for row in reversed(rows):
            if len(row) >= 4 and row[1] == user_id:
                history.append(
                    f"學生：{row[2]}\nAI：{row[3]}"
                )

                if len(history) >= limit:
                    break

        history.reverse()

        return "\n\n".join(history)

    except Exception as e:
        print(f"讀取歷史紀錄失敗: {e}")
        return ""

@app.route("/webhook", methods=['POST'])
def webhook():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_msg = event.message.text
    user_id = event.source.user_id
    try:
        history = get_recent_history(user_id)
        if user_msg == "完整解答":
            prompt = """
            使用者要求完整解答。
        
            請提供：
            1. 題目分析
            2. 解題步驟
            3. 最終答案
            """
        else:
            prompt = f"""
            你是一位解題教學助理。

            以下是學生先前的對話紀錄：
            {history}
            請根據先前教學進度繼續引導。
            規則：
            
            1. 不要直接給答案。
            2. 一次只能給一個提示。
            3. 不要提前透露下一個提示。
            4. 每次回答後都要等待學生回覆。
            5. 若學生回答錯誤，再給下一層提示。
            6. 若學生回答正確，給予鼓勵並繼續引導。
            7. 只有學生明確要求完整解答時，才提供完整解題過程。
            
            回答格式：
            
            【題目分析】
            ...
            
            【第一提示】
            ...
            
            學生問題：
            {user_msg}
            
            最後一定要加上：
            「你覺得下一步該怎麼做呢？」
            """
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        reply = response.text
    except Exception as e:
        print(f'Gemini error: {e}')
        reply = f'錯誤：{str(e)}'
    log_to_sheets(user_id, user_msg, reply)
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply)
    )

if __name__ == "__main__":
    app.run()
