
import httpx
import os
import logging


log = logging.getLogger("fcm_notifier")

def notify_user_fcm(fcm_token: str, title: str, body: str, data: dict = None):
    try:
        log.info("Bağlantısı sağlanacak.")
        return True
    except Exception as e:
        log.error(f"[FCM] Bildirim gönderilemedi: {e}")
        return False

# Test için bir örnek
if __name__ == "__main__":
    # Gerçek FCM token'ı ve içerik ile deneme yapılabilir
    success = notify_user_fcm(
        fcm_token="YOUR_FCM_DEVICE_TOKEN",
        title="Merhaba MikroSalesIQ!",
        body="Bu, Firebase Admin SDK ile gönderilen bir bildirimdir.",
        data={"extra_key": "extra_value"}
    )
    if success:
        print("Bildirim başarıyla gönderildi!")
    else:
        print("Bildirim gönderilemedi.")
