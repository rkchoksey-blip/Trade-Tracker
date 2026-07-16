from flask import Flask, jsonify
from google.oauth2 import service_account
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import robin_stocks.robinhood as rh
from datetime import datetime, timedelta
import os
import json
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

RH_EMAIL = os.getenv('RH_EMAIL')
RH_PASSWORD = os.getenv('RH_PASSWORD')
GOOGLE_SHEETS_ID = os.getenv('GOOGLE_SHEETS_ID')

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

def get_sheets_service():
    creds = None
    
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
    
    return build('sheets', 'v4', credentials=creds)

def login_robinhood():
    try:
        rh.login(username=RH_EMAIL, password=RH_PASSWORD)
        logger.info("✓ Robinhood authenticated")
        return True
    except Exception as e:
        logger.error(f"✗ Robinhood auth failed: {e}")
        return False

def get_robinhood_trades():
    try:
        trades = rh.orders.get_all_orders()
        
        formatted_trades = []
        for order in trades:
            if order['state'] == 'filled':
                trade = {
                    'symbol': order.get('symbol', 'N/A'),
                    'side': order.get('side', ''),
                    'quantity': float(order.get('quantity', 0)),
                    'price': float(order.get('average_price', 0)),
                    'timestamp': order.get('updated_at', ''),
                    'status': order.get('state'),
                }
                formatted_trades.append(trade)
        
        return formatted_trades
    except Exception as e:
        logger.error(f"Robinhood fetch failed: {e}")
        return []

def calculate_trade_pl(trade, current_price=None):
    if trade['side'] == 'buy':
        if current_price:
            pl = (current_price - trade['price']) * trade['quantity']
            pl_pct = ((current_price - trade['price']) / trade['price']) * 100
        else:
            pl = 0
            pl_pct = 0
    else:
        if current_price:
            pl = (trade['price'] - current_price) * trade['quantity']
            pl_pct = ((trade['price'] - current_price) / current_price) * 100
        else:
            pl = 0
            pl_pct = 0
    
    return {
        'pl': round(pl, 2),
        'pl_pct': round(pl_pct, 2)
    }

def update_robinhood_sheet(service, trades):
    if not trades:
        return
    
    try:
        sheet_id = GOOGLE_SHEETS_ID
        range_name = 'Robinhood!A2'
        
        values = []
        for trade in trades[:20]:
            pl = calculate_trade_pl(trade)
            values.append([
                trade['symbol'],
                trade['side'].upper(),
                trade['quantity'],
                trade['price'],
                trade['timestamp'][:10],
                pl['pl'],
                pl['pl_pct']
            ])
        
        body = {'values': values}
        service.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range=range_name,
            valueInputOption='USER_ENTERED',
            body=body
        ).execute()
        
        logger.info(f"✓ Updated Robinhood sheet with {len(trades)} trades")
    except Exception as e:
        logger.error(f"Failed to update Robinhood sheet: {e}")

@app.route('/update-trades', methods=['POST'])
def update_trades():
    try:
        service = get_sheets_service()
        
        if RH_EMAIL and RH_PASSWORD:
            if login_robinhood():
                rh_trades = get_robinhood_trades()
                update_robinhood_sheet(service, rh_trades)
        
        return jsonify({
            'status': 'success',
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Update failed: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'running'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
