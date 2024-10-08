from typing import Set, List, Dict, Any
import requests
import json
import time
import os
from matrix_client.client import MatrixClient, Room
from dotenv import load_dotenv

load_dotenv()

# Configuration
GITLAB_URL: str = "https://git.inpt.fr"
PROJECT_ID: str = "1013"
MATRIX_HOMESERVER: str = "https://matrix.inpt.fr"
MATRIX_USERNAME: str | None = os.environ.get("MATRIX_USERNAME")
MATRIX_PASSWORD: str | None = os.environ.get("MATRIX_PASSWORD")
MATRIX_ROOM_ID: str | None = os.environ.get("MATRIX_ROOM_ID")
CHECK_INTERVAL: int = int(os.environ.get("CHECK_INTERVAL", 300))
STORAGE_FILE: str = "notified_mrs.json"

def load_notified_mrs() -> Set[int]:
    try:
        with open(STORAGE_FILE, 'r') as f:
            return set(json.load(f))
    except FileNotFoundError:
        return set()

def save_notified_mrs(notified_mrs: Set[int]) -> None:
    with open(STORAGE_FILE, 'w') as f:
        json.dump(list(notified_mrs), f)

def get_all_open_mrs() -> List[Dict[str, Any]]:
    url: str = f"{GITLAB_URL}/api/v4/projects/{PROJECT_ID}/merge_requests"
    params: Dict[str, str] = {"state": "opened", "per_page": "100"}
    
    response: requests.Response = requests.get(url, params=params)
    return response.json()

def get_mrs_with_ready_label() -> Set[int]:
    all_mrs = get_all_open_mrs()
    return {mr['iid'] for mr in all_mrs if 'review:ready' in mr.get('labels', [])}

def get_closed_mrs() -> Set[int]:
    url: str = f"{GITLAB_URL}/api/v4/projects/{PROJECT_ID}/merge_requests"
    params: Dict[str, str] = {"state": "closed", "per_page": "100"}
    
    response: requests.Response = requests.get(url, params=params)
    return {mr['iid'] for mr in response.json()}

def clean_notified_mrs(notified_mrs: Set[int]) -> Set[int]:
    closed_mrs = get_closed_mrs()
    ready_mrs = get_mrs_with_ready_label()
    
    # Remove MRs that are closed or no longer have the ready label
    return notified_mrs - closed_mrs - (notified_mrs - ready_mrs)

def send_matrix_message(client: MatrixClient, room_id: str, message: str) -> None:
    room: Room = client.join_room(room_id)
    room.send_html(message, msgtype="m.notice")

def main() -> None:
    if not all([MATRIX_USERNAME, MATRIX_PASSWORD, MATRIX_ROOM_ID]):
        raise ValueError("Missing required environment variables")

    # Set up Matrix client
    client: MatrixClient = MatrixClient(MATRIX_HOMESERVER)
    client.login(username=MATRIX_USERNAME, password=MATRIX_PASSWORD)
    
    # Load previously notified MRs
    notified_mrs: Set[int] = load_notified_mrs()
    
    while True:
        try:
            # Clean up notified MRs (closed or label removed)
            notified_mrs = clean_notified_mrs(notified_mrs)
            save_notified_mrs(notified_mrs)
            
            # Check for new MRs with review:ready label
            all_mrs: List[Dict[str, Any]] = get_all_open_mrs()
            ready_mrs = [mr for mr in all_mrs if 'review:ready' in mr.get('labels', [])]
            
            for mr in ready_mrs:
                mr_id: int = mr['iid']
                if mr_id not in notified_mrs:
                    message: str = f'New merge request ready for review: <a href="{mr["web_url"]}">!{mr_id} {mr["title"]}</a>'
                    send_matrix_message(client, MATRIX_ROOM_ID, message)
                    notified_mrs.add(mr_id)
                    save_notified_mrs(notified_mrs)
            
            time.sleep(CHECK_INTERVAL)
            
        except Exception as e:
            print(f"Error occurred: {e}")
            time.sleep(60)  # Wait a minute before retrying if there's an error

if __name__ == "__main__":
    main()
