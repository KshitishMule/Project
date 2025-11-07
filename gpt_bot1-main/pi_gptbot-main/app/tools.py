import os
from dotenv import load_dotenv
import json
import requests
# Try importing yfinance safely
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

from visionservice import VisionService

load_dotenv()


class AITools:
    def __init__(self, default_language="English", default_internet_market="hu-HU"):
        self.default_language = default_language
        self.default_internet_market = default_internet_market
        self.vision_service = VisionService(default_language=default_language)

    def call_tool(self, tool_name, function_args):
        print("CALLING FUNCTION:", tool_name)

        if tool_name == "get_current_weather":
            func_arg = function_args.get("city_name")
            func_result = self.tool_get_current_weather(func_arg)
        elif tool_name == "search_internet":
            func_arg = function_args.get("query")
            func_result = self.tool_search_internet(func_arg)
        elif tool_name == "get_stock_price":
            func_arg = function_args.get("symbol")
            func_result = self.tool_get_stock_price(func_arg)
        elif tool_name == "get_whats_visible_on_camera":
            func_result = self.vision_service.get_whats_visible_on_camera()
            func_arg = {}
        else:
            return "Unknown tool"

        print(f"FUNCTION CALL RESULTS: {tool_name}({func_arg}) -> {func_result}")
        return func_result

    def get_tools_list(self):
        enable_stock_tool = True
        tools = []

        if enable_stock_tool:
            tools.append({
                "type": "function",
                "function": {
                    "name": "get_stock_price",
                    "description": "Get the stock price for a given symbol",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "symbol": {
                                "type": "string",
                                "description": "The stock symbol, e.g. AAPL",
                            }
                        },
                        "required": ["symbol"],
                    },
                },
            })

        if os.environ.get('AZURE_OPENAI_GPT4V_API_KEY'):
            tools.append({
                "type": "function",
                "function": {
                    "name": "get_whats_visible_on_camera",
                    "description": "Describe what the bot can see using the camera.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                    },
                },
            })

        if os.environ.get('OPENWEATHERMAP_API_KEY'):
            tools.append({
                "type": "function",
                "function": {
                    "name": "get_current_weather",
                    "description": "Get the current weather in a given location",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "city_name": {
                                "type": "string",
                                "description": "The city name, e.g. New York",
                            }
                        },
                        "required": ["city_name"],
                    },
                },
            })

        if os.environ.get('BING_SEARCH_API_KEY'):
            tools.append({
                "type": "function",
                "function": {
                    "name": "search_internet",
                    "description": "Search the internet for up-to-date information or current events",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "What to search for on the internet",
                            }
                        },
                        "required": ["query"],
                    },
                },
            })

        return tools

    def tool_search_internet(self, query):
        subscription_key = os.environ.get('BING_SEARCH_API_KEY')
        if not subscription_key:
            return "❌ Bing Search API key not found."

        response = requests.get(
            "https://api.bing.microsoft.com/v7.0/search",
            headers={'Ocp-Apim-Subscription-Key': subscription_key},
            params={'q': query, 'mkt': self.default_internet_market, "count": 3}
        )

        if response.status_code != 200:
            return f"Error: Bing API returned {response.status_code}"

        webpage_results = ''
        for webpage in response.json().get('webPages', {}).get('value', []):
            webpage_results += f"{webpage['name']} | {webpage['snippet']}\n"

        return webpage_results or "No results found."

    def tool_get_stock_price(self, symbol):
        if not YFINANCE_AVAILABLE:
            print("⚠️  yfinance not installed — skipping stock price lookup")
            return "Stock price lookup not available on this device."

        stock_info = yf.Ticker(symbol)
        price = stock_info.info.get('currentPrice')
        if price:
            return f"{symbol} current price: {price}"
        else:
            return f"Could not fetch stock price for {symbol}"

    def tool_get_current_weather(self, city_name):
        open_weather_api_key = os.environ.get('OPENWEATHERMAP_API_KEY')
        if not open_weather_api_key:
            return "❌ OpenWeatherMap API key not found."

        complete_url = (
            "http://api.openweathermap.org/data/2.5/weather?"
            f"appid={open_weather_api_key}&units=metric&q={city_name}"
        )
        response = requests.get(complete_url).json()

        if response.get("cod") != 200:
            return f"Error: {response.get('message', 'Unable to fetch weather')}"

        return json.dumps({
            "city": city_name,
            "temperature": response["main"]["temp"],
            "description": response["weather"][0]["description"]
        }, indent=2)
