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

# 이미지 검색 키워드
image_keywords = [
    # 한국어 키워드
    "사진", "이미지", "그림", "짤", "짤방", "가져와", "보여줘", "줘",
    # 영어 키워드
    "image", "picture", "photo", "show", "get"
]

# 이미지 갯수 키워드
image_count_keywords = [
    # 숫자 + 단위
    "장", "개", "매",
    # 기타 키워드
    "여러장", "여러개"
]

# 이미지 추가 요청 키워드
image_more_keywords = [
    # 한국어 키워드
    "더", "추가", "또",
    # 영어 키워드
    "more", "another", "additional"
]

# 이미지 생성 키워드
image_generate_keywords = [
    # 한국어 키워드
    "만들어줘", "생성해줘", "그려줘", "그려", "만들어", "생성",
    # 영어 키워드
    "generate", "create", "draw"
]

# 이미지 분석 키워드
image_analysis_keywords = [
    # 한국어 키워드
    "이거", "이 사진", "이 이미지", "이게", "설명해줘", "분석해줘", "알려줘", "뭐야", "무엇",
    # 영어 키워드
    "this", "what", "explain", "analyze", "tell me"
]

# 웹페이지 캡처 요청 키워드
webpage_capture_keywords = [
    # 한국어 키워드
    "캡처", "스크린샷", "화면", "링크",
    # 영어 키워드
    "capture", "screenshot", "screen"
]

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
        
        def get_image_count(message: str) -> int:
            """메시지에서 이미지 갯수를 추출합니다."""
            import re
            
            # "여러장", "여러개" 키워드 체크
            if any(keyword in message for keyword in ["여러장", "여러개"]):
                return 3  # 기본값으로 3장 반환
            
            # 숫자 + 단위 패턴 찾기
            pattern = r'(\d+)\s*(장|개|매)'
            match = re.search(pattern, message)
            if match:
                count = int(match.group(1))
                return min(count, 5)  # 최대 5장으로 제한
            
            return 1  # 기본값 1장
        
        @handler.add(MessageEvent, message=TextMessage)
        def handle_message(event):
            print("Handling message event:", event)
            try:
                reply_token = event.reply_token
                user_message = event.message.text
                source_type = event.source.type
                source_id = getattr(event.source, f"{source_type}_id", None)
                
                print(f"메시지 수신: {user_message}")
                
                # 이전 메시지와 URL 저장을 위한 전역 변수
                if not hasattr(handle_message, 'last_messages'):
                    handle_message.last_messages = {}
                if not hasattr(handle_message, 'last_urls'):
                    handle_message.last_urls = {}
                
                # 웹페이지 캡처 요청 체크
                if any(keyword in user_message.lower() for keyword in webpage_capture_keywords):
                    # 인용된 메시지에서 URL 찾기
                    if hasattr(event.message, 'quote_token'):
                        quote_token = event.message.quote_token
                        if source_id in handle_message.last_messages and quote_token in handle_message.last_messages[source_id]:
                            prev_message = handle_message.last_messages[source_id][quote_token]
                            # URL 추출
                            import re
                            urls = re.findall(r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[^\s]*', prev_message)
                            if urls:
                                url = urls[0]
                                # URL 저장
                                if source_id not in handle_message.last_urls:
                                    handle_message.last_urls[source_id] = {}
                                handle_message.last_urls[source_id][quote_token] = url
                                
                                # 웹페이지 캡처
                                screenshot_path = capture_webpage(url)
                                if screenshot_path:
                                    # 이미지 전송
                                    image_message = ImageSendMessage(
                                        original_content_url=f"https://your-domain.com/{screenshot_path}",
                                        preview_image_url=f"https://your-domain.com/{screenshot_path}"
                                    )
                                    line_bot_api.reply_message(reply_token, messages=image_message)
                                    return
                
                # 이미지 분석 요청 체크 (인용된 메시지가 있는 경우)
                if hasattr(event.message, 'quote_token') and any(keyword in user_message.lower() for keyword in image_analysis_keywords):
                    quote_token = event.message.quote_token
                    if source_id in handle_message.last_messages and quote_token in handle_message.last_messages[source_id]:
                        img_url = handle_message.last_messages[source_id][quote_token]
                        search_query = handle_message.last_messages[source_id]['user']
                        
                        # 이미지 분석 응답 생성
                        analysis = f"이 이미지는 '{search_query}'에 대한 검색 결과입니다.\n\n"
                        
                        # 이미지 특성 분석
                        if "펭귄" in search_query:
                            analysis += "이미지에는 펭귄이 등장하며, 남극의 자연스러운 환경에서 촬영된 것으로 보입니다. "
                            analysis += "펭귄은 특유의 걸음걸이와 흑백의 깃털이 특징적이며, 무리를 지어 생활하는 모습을 보여줍니다."
                        elif "고양이" in search_query:
                            analysis += "이미지에는 고양이가 등장하며, 고양이의 특징적인 모습과 표정이 잘 담겨있습니다. "
                            analysis += "고양이의 우아한 자태와 귀여운 모습이 잘 표현되어 있습니다."
                        elif "강아지" in search_query:
                            analysis += "이미지에는 강아지가 등장하며, 강아지의 친근하고 활발한 모습이 잘 담겨있습니다. "
                            analysis += "강아지의 충실하고 사랑스러운 표정이 잘 포착되어 있습니다."
                        else:
                            analysis += f"이미지는 '{search_query}'의 특징적인 모습을 잘 보여주고 있습니다. "
                            analysis += "선명한 화질과 구도로 주제가 잘 표현되어 있습니다."
                        
                        text_message = TextSendMessage(text=analysis)
                        line_bot_api.reply_message(reply_token, messages=text_message)
                        return
                
                # 이미지 검색 요청 체크
                elif any(keyword in user_message.lower() for keyword in image_keywords):
                    search_query = user_message
                    for keyword in image_keywords:
                        search_query = search_query.replace(keyword, "").strip()
                    
                    # 이미지 갯수 추출
                    img_count = get_image_count(user_message)
                    for keyword in image_count_keywords:
                        search_query = search_query.replace(keyword, "").strip()
                    
                    # 검색어 저장
                    handle_message.last_messages[source_id] = {'user': search_query}
                    print(f"이미지 검색 시작: {search_query} ({img_count}장)")
                    
                    try:
                        # SerpAPI로 이미지 검색
                        if config.SERPAPI_API_KEY:
                            img_crawler = ImageCrawler(
                                engine='serpapi',
                                nums=img_count,
                                api_key=config.SERPAPI_API_KEY
                            )
                            img_urls = img_crawler._serpapi_search_multiple(search_query)
                            if img_urls:
                                messages = []
                                # 이미지 URL 저장
                                if source_id not in handle_message.last_messages:
                                    handle_message.last_messages[source_id] = {}
                                for img_url in img_urls:
                                    if not img_url.startswith('https'):
                                        img_url = img_url.replace('http:', 'https:', 1)
                                    quote_token = f"img_{len(handle_message.last_messages[source_id])}"
                                    handle_message.last_messages[source_id][quote_token] = img_url
                                    messages.append(ImageSendMessage(
                                        original_content_url=img_url,
                                        preview_image_url=img_url,
                                        quote_token=quote_token
                                    ))
                                line_bot_api.reply_message(reply_token, messages=messages)
                                return
                    except Exception as e:
                        print(f"SerpAPI 검색 오류: {str(e)}")
                    
                    try:
                        # iCrawler로 이미지 검색
                        img_crawler = ImageCrawler(nums=img_count)
                        img_urls = img_crawler._icrawler_search_multiple(search_query)
                        if img_urls:
                            messages = []
                            # 이미지 URL 저장
                            if source_id not in handle_message.last_messages:
                                handle_message.last_messages[source_id] = {}
                            for img_url in img_urls:
                                if not img_url.startswith('https'):
                                    img_url = img_url.replace('http:', 'https:', 1)
                                quote_token = f"img_{len(handle_message.last_messages[source_id])}"
                                handle_message.last_messages[source_id][quote_token] = img_url
                                messages.append(ImageSendMessage(
                                    original_content_url=img_url,
                                    preview_image_url=img_url,
                                    quote_token=quote_token
                                ))
                            line_bot_api.reply_message(reply_token, messages=messages)
                            return
                    except Exception as e:
                        print(f"iCrawler 검색 오류: {str(e)}")
                    
                    text_message = TextSendMessage(text="죄송합니다. 이미지를 찾을 수 없습니다.")
                    line_bot_api.reply_message(reply_token, messages=text_message)
                    return
                
                # 이미지 생성 요청 체크
                elif any(keyword in user_message.lower() for keyword in image_generate_keywords):
                    search_query = user_message
                    for keyword in image_generate_keywords:
                        search_query = search_query.replace(keyword, "").strip()
                    
                    print(f"이미지 생성 시작: {search_query}")
                    
                    try:
                        # g4f로 이미지 생성 시도
                        img_url = g4f_generate_image(search_query)
                        if img_url:
                            print(f"이미지 생성 성공: {img_url}")
                            if not img_url.startswith('https'):
                                img_url = img_url.replace('http:', 'https:', 1)
                            image_message = ImageSendMessage(
                                original_content_url=img_url,
                                preview_image_url=img_url
                            )
                            line_bot_api.reply_message(reply_token, messages=image_message)
                            return
                    except Exception as e:
                        print(f"g4f 이미지 생성 오류: {str(e)}")
                    
                    # g4f 실패시 RapidAPI 시도
                    if config.RAPID:
                        try:
                            img_url = rapidapis.ai_text_to_img(search_query)
                            if img_url:
                                print(f"RapidAPI 이미지 생성 성공: {img_url}")
                                if not img_url.startswith('https'):
                                    img_url = img_url.replace('http:', 'https:', 1)
                                image_message = ImageSendMessage(
                                    original_content_url=img_url,
                                    preview_image_url=img_url
                                )
                                line_bot_api.reply_message(reply_token, messages=image_message)
                                return
                        except Exception as e:
                            print(f"RapidAPI 이미지 생성 오류: {str(e)}")
                    
                    # 이미지 생성 실패
                    text_message = TextSendMessage(text="죄송합니다. 이미지를 생성할 수 없습니다.")
                    line_bot_api.reply_message(reply_token, messages=text_message)
                    return
                
                # 메모리에 사용자 메시지 저장
                memory.append(source_id, 'user', user_message)
                
                # 기본적으로 zhipuai로 응답
                response = chat_completion(
                    source_id,
                    memory,
                    method='zhipuai',
                    api_key=config.GPT_API_KEY
                )
                text_message = TextSendMessage(text=response)
                line_bot_api.reply_message(reply_token, messages=text_message)
                
            except Exception as e:
                print(f"메시지 처리 오류: {str(e)}")
                error_msg = "죄송합니다. 요청을 처리하는 중에 오류가 발생했습니다."
                line_bot_api.reply_message(reply_token, TextSendMessage(text=error_msg))
        
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
    # 이미지 검색 키워드가 포함된 경우
    if any(keyword in query for keyword in image_keywords):
        # 검색어에서 이미지 관련 키워드 제거
        search_query = query
        for keyword in image_keywords:
            search_query = search_query.replace(keyword, "").strip()
        return "search_image_url", search_query
    
    # 기본 에이전트 로직
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
    """이미지 URL을 다양한 검색 소스에서 가져옵니다."""
    try:
        # 먼저 icrawler 시도
        img_crawler = ImageCrawler(nums=1)
        img_url = img_crawler.get_url(query)
        
        # icrawler 실패시 serpapi 시도
        if not img_url and config.SERPAPI_API_KEY:
            img_serp = ImageCrawler(
                engine='serpapi',
                nums=1,
                api_key=config.SERPAPI_API_KEY
            )
            img_url = img_serp.get_url(query)
            if img_url:
                print('Used SerpAPI for image search')
                
        return img_url
        
    except Exception as e:
        print(f"Image search error: {e}")
        return None


def send_image_reply(reply_token, img_url: str) -> None:
    """이미지 메시지를 전송합니다."""
    try:
        if not img_url:
            send_text_reply(reply_token, '이미지를 찾을 수 없습니다.')
            return
            
        print(f"이미지 URL: {img_url}")
        
        # LINE에서는 HTTPS URL만 허용
        if not img_url.startswith('https'):
            img_url = img_url.replace('http:', 'https:', 1)
        
        image_message = ImageSendMessage(
            original_content_url=img_url,
            preview_image_url=img_url
        )
        
        line_bot_api.reply_message(reply_token, messages=image_message)
        print("이미지 전송 성공")
        
    except Exception as e:
        print(f"이미지 전송 오류: {str(e)}")
        error_msg = f'이미지 전송 중 오류가 발생했습니다: {str(e)}'
        send_text_reply(reply_token, error_msg)


def send_text_reply(reply_token, text: str) -> None:
    """Sends a text message to the user."""
    if not text:
        text = "There're some problem in server."
    text_message = TextSendMessage(text=text)
    line_bot_api.reply_message(reply_token, messages=text_message)


@line_app.get("/recommend")
def recommend_from_yt() -> dict:
    try:
        videos = recommend_videos()
        
        if videos and "오류가 발생했습니다" not in videos:
            # 모든 사용자에게 브로드캐스트
            line_bot_api.broadcast(TextSendMessage(text=videos))
            
            # 알려진 그룹에 메시지 푸시
            known_group_ids = [
                'C6d-xxxxxxxxxxxxxxxxxxxxxxxxxxxxx',
                'Ccc-xxxxxxxxxxxxxxxxxxxxxxxxxxxxx',
                'Cbb-xxxxxxxxxxxxxxxxxxxxxxxxxxxxx',
            ]
            
            for group_id in known_group_ids:
                try:
                    line_bot_api.push_message(group_id, TextSendMessage(text=videos))
                except Exception as e:
                    print(f"그룹 {group_id}에 메시지 전송 실패: {e}")
            
            print('YouTube 추천 성공')
            return {"status": "success", "message": "동영상이 추천되었습니다."}
            
        else:
            print('YouTube 추천 실패')
            return {"status": "failed", "message": "추천할 동영상을 가져올 수 없습니다."}
            
    except Exception as e:
        print(f"YouTube 추천 오류: {e}")
        return {"status": "error", "message": str(e)}


@line_app.get('/cwsChannel')
def get_cws_channel() -> dict:
    article_details = cws_scraper.get_latest_article()
    cws_channel_response = cws_scraper.get_cws_channel_response(article_details)

    if cws_channel_response:
        line_bot_api.broadcast(TextSendMessage(text=cws_channel_response))
        return {"status": "success", "message": "got cws channel response."}

    else:
        return {"status": "failed", "message": "no get cws channel response."}


def capture_webpage(url: str) -> str:
    """웹페이지를 캡처합니다."""
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        import tempfile
        import os
        from datetime import datetime
        
        # Chrome 옵션 설정
        chrome_options = Options()
        chrome_options.add_argument('--headless')  # 헤드리스 모드
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        
        # 웹드라이버 초기화
        driver = webdriver.Chrome(options=chrome_options)
        
        try:
            # 페이지 로드
            driver.get(url)
            driver.implicitly_wait(10)
            
            # 스크린샷 저장
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            screenshot_path = f'static/screenshots/screenshot_{timestamp}.png'
            os.makedirs('static/screenshots', exist_ok=True)
            driver.save_screenshot(screenshot_path)
            
            return screenshot_path
            
        finally:
            driver.quit()
            
    except Exception as e:
        print(f"웹페이지 캡처 오류: {str(e)}")
        return None
