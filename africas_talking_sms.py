import requests
import os

AT_URL = "https://api.africastalking.com/version1/messaging/bulk"

def send_sms(phone, message):
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "apiKey": os.getenv("AT_API_KEY")
    }

    payload = {
        "username": os.getenv("AT_USERNAME"),
        "message": message,
        "phoneNumbers": [phone]
        # ❌ DO NOT include senderId yet
    }

    try:
        response = requests.post(AT_URL, json=payload, headers=headers)
        data = response.json()

        print("AT RESPONSE:", data)

        # Extract status
        recipients = data.get("SMSMessageData", {}).get("Recipients", [])

        if not recipients:
            return False, "No recipient response"

        status_code = recipients[0].get("statusCode")

        # Success codes from docs:
        # 100: Processed, 101: Sent, 102: Queued
        if status_code in [100, 101, 102]:
            return True, data
        else:
            return False, recipients[0]

    except Exception as e:
        return False, str(e)
