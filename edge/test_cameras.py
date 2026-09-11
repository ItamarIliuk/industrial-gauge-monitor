import cv2
import os

def test_cameras():
    print("=== Digital Gauge Monitor - Camera Scanner ===")
    debug_dir = "debug_captures"
    os.makedirs(debug_dir, exist_ok=True)
    
    found_any = False
    
    # Scan indices from 0 to 5
    for index in range(6):
        # Test Default Backend
        cap = cv2.VideoCapture(index)
        if cap.isOpened():
            ret, frame = cap.read()
            if ret:
                filename = os.path.join(debug_dir, f"camera_{index}_default.jpg")
                cv2.imwrite(filename, frame)
                print(f"[SUCCESS] Index {index} (Default backend) is ACTIVE. Saved frame to {filename}")
                found_any = True
            else:
                print(f"[WARNING] Index {index} (Default backend) opened but failed to read frame.")
            cap.release()
        else:
            print(f"[INFO] Index {index} (Default backend) is not available.")
            
        # Test DirectShow Backend (highly recommended on Windows for USB cams)
        cap_dshow = cv2.VideoCapture(index + cv2.CAP_DSHOW)
        if cap_dshow.isOpened():
            ret, frame = cap_dshow.read()
            if ret:
                filename = os.path.join(debug_dir, f"camera_{index}_dshow.jpg")
                cv2.imwrite(filename, frame)
                print(f"[SUCCESS] Index {index} (DirectShow backend) is ACTIVE. Saved frame to {filename}")
                found_any = True
            else:
                print(f"[WARNING] Index {index} (DirectShow backend) opened but failed to read frame.")
            cap_dshow.release()
            
    if not found_any:
        print("[ERROR] No active cameras were found on indices 0-5.")
    else:
        print("\n=== Scan complete! Check the 'debug_captures' folder to see the images and choose your index. ===")

if __name__ == "__main__":
    test_cameras()
