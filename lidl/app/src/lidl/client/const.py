"""Constants of the Lidl Plus mobile API (from Przemko92/home-assistant-lidlplus, MIT; trimmed)."""

from typing import Final

AUTH_BASE: Final = "https://accounts.lidl.com"
AUTH_URL: Final = f"{AUTH_BASE}/connect/authorize"
TOKEN_URL: Final = f"{AUTH_BASE}/connect/token"
CLIENT_ID: Final = "LidlPlusNativeClient"
CLIENT_SECRET: Final = "secret"
REDIRECT_URI: Final = "com.lidlplus.app://callback"
AUTH_SCOPES: Final = "openid profile offline_access lpprofile lpapis"
APP_VERSION: Final = "17.9.3"
APP_PACKAGE: Final = "com.lidl.eci.lidlplus"
OPERATING_SYSTEM: Final = "Android"
OS_VERSION: Final = "14"
API_USER_AGENT: Final = (
    "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36"
)
PROFILE_BASE: Final = "https://profile.lidlplus.com/api"
TICKETS_BASE: Final = "https://tickets.lidlplus.com/api"
COUPONS_BASE: Final = "https://coupons.lidlplus.com/app/api"
SEGMENTS_BASE: Final = "https://segments.lidlplus.com/api"
LOTTERY_BASE: Final = "https://purchaselottery.lidlplus.com/api"
COUPON_PLUS_BASE: Final = "https://couponplus.lidlplus.com/api"
COUNTRIES_URL: Final = "https://appgateway.lidlplus.com/configurationapp/v3/countries"
ACTION_LOCATION: Final = "COUPON_LIST"
