import sys
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import *

from chatgpt_linebot.memory import Memory
from chatgpt_linebot.modules import (
    CWArticleScraper,
    Horoscope,
    ImageCrawler,
    RapidAPIs,
    chat,
    chat_completion,
    g4f_generate_image,
    recommend_videos,
)
from chatgpt_linebot.prompts import agent_template, girlfriend

sys.path.append(".")

import config

line_app = APIRouter()
memory = Memory(3)
horoscope = Horoscope()
rapidapis = RapidAPIs(config.RAPID)
cws_scraper = CWArticleScraper()

line_bot_api = LineBotApi(config.LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(config.LINE_CHANNEL_SECRET)


@line_app.post("/callback")
async def callback(request: Request) -> str:
    """LINE Bot webhook callback"""
    try:
        signature = request.headers["X-Line-Signature"]
        body = await request.body()
        body_decode = body.decode('utf-8')
        
        print("Request body:", body_decode)  # 디버깅을 위한 출력
        print("Signature:", signature)  # 시그니처 확인
        print("Channel Secret:", config.LINE_CHANNEL_SECRET)  # 시크릿 키 확인
        
        # handler를 새로 생성
        handler = WebhookHandler(config.LINE_CHANNEL_SECRET)
        
        @handler.add(MessageEvent, message=TextMessage)
        def handle_message(event):
            print("Handling message event:", event)  # 이벤트 처리 확인
            try:
                reply_token = event.reply_token
                user_message = event.message.text
                
                # 메모리에 사용자 메시지 저장
                memory.append(event.source.user_id, 'user', user_message)
                
                # zhipuai를 사용하여 응답 생성
                response = chat_completion(
                    event.source.user_id,
                    memory,
                    method='zhipuai',
                    api_key=config.GPT_API_KEY
                )
                
                # 응답 전송
                line_bot_api.reply_message(
                    reply_token,
                    TextSendMessage(text=response)
                )
                
            except Exception as e:
                print("Error in handle_message:", str(e))
                
        handler.handle(body_decode, signature)
        
    except InvalidSignatureError as e:
        print("Invalid signature error:", str(e))
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        print("Error occurred:", str(e))
        raise HTTPException(status_code=500, detail=str(e))
        
    return "OK"


def is_url(string: str) -> bool:
    try:
        result = urlparse(string)
        return all([result.scheme, result.netloc])
    except ValueError:
        return False


def agent(query: str) -> tuple[str]:
    """Auto use correct tool by user query."""
    prompt = agent_template + query
    message = [{'role': 'user', 'content': prompt}]

    tool, input = chat(message, config.GPT_METHOD, config.GPT_API_KEY).split(', ')

    print(f"""
    Agent
    =========================================
    Query: {query}
    Tool: {tool}
    Input: {input}
    """)

    return tool, input


def search_image_url(query: str) -> str:
    """Fetches image URL from different search sources."""
    img_crawler = ImageCrawler(nums=5)
    img_url = img_crawler.get_url(query)
    if not img_url:
        img_serp = ImageCrawler(engine='serpapi', nums=5, api_key=config.SERPAPI_API_KEY)
        img_url = img_serp.get_url(query)
        print('Used Serpapi search image instead of icrawler.')
    return img_url


def send_image_reply(reply_token, img_url: str) -> None:
    """Sends an image message to the user."""
    if not img_url:
        send_text_reply(reply_token, 'Cannot get image.')
    image_message = ImageSendMessage(original_content_url=img_url, preview_image_url=img_url)
    line_bot_api.reply_message(reply_token, messages=image_message)


def send_text_reply(reply_token, text: str) -> None:
    """Sends a text message to the user."""
    if not text:
        text = "There're some problem in server."
    text_message = TextSendMessage(text=text)
    line_bot_api.reply_message(reply_token, messages=text_message)


@handler.add(MessageEvent, message=(TextMessage))
def handle_message(event) -> None:
    """Event - User sent message

    Args:
        event (LINE Event Object)

    Refs:
        https://developers.line.biz/en/reference/messaging-api/#message-event
        https://www.21cs.tw/Nurse/showLiangArticle.xhtml?liangArticleId=503
    """
    if not isinstance(event.message, TextMessage):
        return

    reply_token = event.reply_token
    user_message = event.message.text

    source_type = event.source.type
    source_id = getattr(event.source, f"{source_type}_id", None)

    if source_type == 'user':
        user_name = line_bot_api.get_profile(source_id).display_name
        print(f'{user_name}: {user_message}')

    else:
        if not user_message.startswith('@chat'):
            return
        else:
            user_message = user_message.replace('@chat', '')

    tool, input_query = agent(user_message)

    if tool in ['chat_completion']:
        input_query = f"{girlfriend}:\n {input_query}"
        memory.append(source_id, 'user', f"{girlfriend}:\n {user_message}")

    try:
        if tool in ['chat_completion']:
            response = chat_completion(source_id, memory, config.GPT_METHOD, config.GPT_API_KEY)
        else:
            response = eval(f"{tool}('{input_query}')")

        if is_url(response):
            send_image_reply(reply_token, response)
        else:
            send_text_reply(reply_token, response)

    except Exception as e:
        send_text_reply(reply_token, e)


@line_app.get("/recommend")
def recommend_from_yt() -> dict:
    """Line Bot Broadcast

    Descriptions
    ------------
    Recommend youtube videos to all followed users.
    (Use cron-job.org to call this api)

    References
    ----------
    https://www.cnblogs.com/pungchur/p/14385539.html
    https://steam.oxxostudio.tw/category/python/example/line-push-message.html
    """
    videos = recommend_videos()

    if videos and "There're something wrong in openai api when call, please try again." not in videos:
        line_bot_api.broadcast(TextSendMessage(text=videos))

        # Push message to group via known group (event.source.group_id)
        known_group_ids = [
            'C6d-xxxxxxxxxxxxxxxxxxxxxxxxxxxxx',
            'Ccc-xxxxxxxxxxxxxxxxxxxxxxxxxxxxx',
            'Cbb-xxxxxxxxxxxxxxxxxxxxxxxxxxxxx',
        ]
        for group_id in known_group_ids:
            line_bot_api.push_message(group_id, TextSendMessage(text=videos))

        print('Successfully recommended videos')
        return {"status": "success", "message": "recommended videos."}

    else:
        print('Failed recommended videos')
        return {"status": "failed", "message": "no get recommended videos."}


@line_app.get('/cwsChannel')
def get_cws_channel() -> dict:
    article_details = cws_scraper.get_latest_article()
    cws_channel_response = cws_scraper.get_cws_channel_response(article_details)

    if cws_channel_response:
        line_bot_api.broadcast(TextSendMessage(text=cws_channel_response))
        return {"status": "success", "message": "got cws channel response."}

    else:
        return {"status": "failed", "message": "no get cws channel response."}
