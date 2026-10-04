import pyautogui
import easyocr
import numpy as np
from PIL import Image
import cv2

import os

class VisionHelper:
    def __init__(self):
        print("正在載入隨附的辨識模型...")
        self.model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
        if not os.path.exists(self.model_path):
            os.makedirs(self.model_path)

        try:
            self.reader = easyocr.Reader(
                ['ch_tra', 'en'],
                model_storage_directory=self.model_path,
                download_enabled=False,
            )
            print("辨識引擎初始化完成。")
        except Exception as e:
            print(f"辨識引擎裝載失敗: {e}")
            raise
    
    def find_text_position(self, target_text="調劑日期", window_title=None):
        """
        在指定視窗或全螢幕中尋找文字位置
        """
        try:
            # 1. 擷取螢幕並進行影像強化
            screenshot = pyautogui.screenshot()
            screenshot_np = np.array(screenshot)
            
            # 轉換為灰階
            gray = cv2.cvtColor(screenshot_np, cv2.COLOR_RGB2GRAY)
            
            # 2. 進行 OCR 辨識
            results = self.reader.readtext(gray)
            
            # 3. 搜尋目標文字 (支援模糊比對)
            target_keywords = ["調劑日期", "調劑", "日期"]
            
            for keyword in target_keywords:
                for (bbox, text, prob) in results:
                    # 去除空白再比對
                    clean_text = text.replace(" ", "")
                    if keyword in clean_text:
                        center_x = int((bbox[0][0] + bbox[2][0]) / 2)
                        center_y = int((bbox[0][1] + bbox[2][1]) / 2)
                        print(f"成功定位到關鍵字 '{text}' (搜尋目標: {keyword})，座標: ({center_x}, {center_y})")
                        return center_x, center_y
            
            # 如果還是找不到，列出前 10 個辨識到的文字以便除錯
            found_texts = [res[1] for res in results]
            print(f"辨識失敗。目前畫面上看見的文字有：{found_texts[:10]}")
            return None
        except Exception as e:
            print(f"辨識過程中發生錯誤: {e}")
            return None

if __name__ == "__main__":
    helper = VisionHelper()
    pos = helper.find_text_position("調劑日期")
    if pos:
        print(f"測試成功：中心點為 {pos}")
    else:
        print("測試失敗：未找到文字")
