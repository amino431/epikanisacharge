from flask import Flask, request, jsonify
import stripe
import concurrent.futures
import uuid
import time
import threading

app = Flask(__name__)

# مفاتيح Stripe
stripe.api_key = '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'
stripe.api_version = '2018-11-08'

# تنفيذ متعدد الخيوط لمعالجة الطلبات بشكل متوازي
executor = concurrent.futures.ThreadPoolExecutor(max_workers=20)

# تخزين النتائج مع وقت انتهاء الصلاحية (60 ثانية)
results = {}
results_lock = threading.Lock()

def cleanup_old_results():
    """تنظيف النتائج القديمة كل دقيقة"""
    while True:
        time.sleep(60)
        current_time = time.time()
        with results_lock:
            keys_to_delete = [k for k, v in results.items() if current_time - v['timestamp'] > 60]
            for key in keys_to_delete:
                del results[key]

# بدء خيط لتنظيف النتائج القديمة
cleanup_thread = threading.Thread(target=cleanup_old_results, daemon=True)
cleanup_thread.start()

def process_charge_async(token_id, amount, request_id):
    """معالجة عملية الدفع بشكل غير متزامن مع التقاط جميع تفاصيل الخطأ"""
    try:
        charge = stripe.Charge.create(
            amount=amount,
            currency='usd',
            source=token_id,
            description='$1 Donation'
        )
        
        if charge.status == 'succeeded':
            result = {
                'success': True, 
                'message': 'Payment was successful. Thank you for your donation!',
                'timestamp': time.time()
            }
        else:
            result = {
                'success': False, 
                'message': f'Payment failed with status: {charge.status}',
                'timestamp': time.time()
            }
            
    except stripe.error.CardError as e:
        # خطأ في البطاقة (تم رفضها)
        body = e.json_body
        err = body.get('error', {})
        result = {
            'success': False,
            'message': f"Card error: {err.get('message')}",
            'code': err.get('code'),
            'decline_code': err.get('decline_code'),
            'timestamp': time.time()
        }
        
    except stripe.error.RateLimitError as e:
        # طلبات كثيرة جدًا
        result = {
            'success': False,
            'message': 'Rate limit error. Please try again later.',
            'timestamp': time.time()
        }
        
    except stripe.error.InvalidRequestError as e:
        # معاملات غير صالحة
        result = {
            'success': False,
            'message': f'Invalid parameters: {str(e)}',
            'timestamp': time.time()
        }
        
    except stripe.error.AuthenticationError as e:
        # فشل المصادقة
        result = {
            'success': False,
            'message': 'Authentication error. Please contact support.',
            'timestamp': time.time()
        }
        
    except stripe.error.APIConnectionError as e:
        # خطأ في اتصال الشبكة
        result = {
            'success': False,
            'message': 'Network error. Please try again.',
            'timestamp': time.time()
        }
        
    except stripe.error.StripeError as e:
        # خطأ عام في Stripe
        result = {
            'success': False,
            'message': f'Stripe error: {str(e)}',
            'timestamp': time.time()
        }
        
    except Exception as e:
        # خطأ غير متوقع
        result = {
            'success': False,
            'message': f'Unexpected error: {str(e)}',
            'timestamp': time.time()
        }
    
    # تخزين النتيجة
    with results_lock:
        results[request_id] = result

@app.route('/')
def index():
    return '''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Donation Page</title>
        <script src="https://js.stripe.com/v3/"></script>
        <style>
            body {
                font-family: Arial, sans-serif;
                max-width: 500px;
                margin: 50px auto;
                padding: 20px;
                background-color: #f5f5f5;
            }
            .container {
                background-color: white;
                padding: 30px;
                border-radius: 8px;
                box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
            }
            h1 {
                color: #333;
                text-align: center;
            }
            .form-group {
                margin-bottom: 20px;
            }
            label {
                display: block;
                margin-bottom: 5px;
                font-weight: bold;
            }
            input, .StripeElement {
                width: 100%;
                padding: 10px;
                border: 1px solid #ddd;
                border-radius: 4px;
                box-sizing: border-box;
            }
            button {
                width: 100%;
                padding: 12px;
                background-color: #6772E5;
                color: white;
                border: none;
                border-radius: 4px;
                cursor: pointer;
                font-size: 16px;
            }
            button:hover {
                background-color: #5469D4;
            }
            button:disabled {
                background-color: #cccccc;
                cursor: not-allowed;
            }
            #card-errors {
                color: #E25950;
                margin-top: 10px;
                min-height: 20px;
            }
            .success-message {
                color: green;
                text-align: center;
                font-weight: bold;
                margin-top: 20px;
            }
            .error-message {
                color: red;
                text-align: center;
                font-weight: bold;
                margin-top: 20px;
            }
            .processing {
                text-align: center;
                display: none;
                margin-top: 20px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Donate $1</h1>
            <form id="payment-form">
                <div class="form-group">
                    <label for="card-element">Credit or debit card</label>
                    <div id="card-element">
                        <!-- A Stripe Element will be inserted here. -->
                    </div>
                    <div id="card-errors" role="alert"></div>
                </div>
                <button type="submit">Donate $1</button>
            </form>
            <div id="processing" class="processing">
                <p>Processing your donation...</p>
            </div>
            <div id="success-message" class="success-message" style="display: none;"></div>
            <div id="error-message" class="error-message" style="display: none;"></div>
        </div>

        <script>
            // Initialize Stripe.js with your publishable key
            var stripe = Stripe('pk_live_51QbtuVH73YuEGCm0XPyynaERUFIGoVSwxHmSZZVDkDhitdrU2sXXq3UP0WOFCUMYhrPBXTUTDRQKL5FEMIVlra0F00lBg83g1J');
            
            // Create an instance of Elements
            var elements = stripe.elements();
            
            // Custom styling can be passed to options when creating an Element
            var style = {
                base: {
                    color: '#32325d',
                    fontFamily: '"Helvetica Neue", Helvetica, sans-serif',
                    fontSmoothing: 'antialiased',
                    fontSize: '16px',
                    '::placeholder': {
                        color: '#aab7c4'
                    }
                },
                invalid: {
                    color: '#fa755a',
                    iconColor: '#fa755a'
                }
            };
            
            // Create an instance of the card Element
            var card = elements.create('card', {style: style});
            
            // Add an instance of the card Element into the `card-element` <div>
            card.mount('#card-element');
            
            // Handle real-time validation errors from the card Element
            card.addEventListener('change', function(event) {
                var displayError = document.getElementById('card-errors');
                if (event.error) {
                    displayError.textContent = event.error.message;
                } else {
                    displayError.textContent = '';
                }
            });
            
            // Handle form submission
            var form = document.getElementById('payment-form');
            form.addEventListener('submit', function(event) {
                event.preventDefault();
                
                // Disable submit button to prevent repeated clicks
                document.querySelector('button').disabled = true;
                document.getElementById('processing').style.display = 'block';
                document.getElementById('card-errors').textContent = '';
                document.getElementById('error-message').style.display = 'none';
                
                // Create token with card Element
                stripe.createToken(card).then(function(result) {
                    if (result.error) {
                        // Show error to your customer
                        document.getElementById('card-errors').textContent = result.error.message;
                        document.getElementById('processing').style.display = 'none';
                        document.querySelector('button').disabled = false;
                    } else {
                        // Send token ID to your server
                        stripeTokenHandler(result.token.id);
                    }
                });
            });
            
            function stripeTokenHandler(tokenId) {
                // Generate a unique request ID
                var requestId = 'req_' + new Date().getTime() + '_' + Math.random().toString(36).substr(2, 9);
                
                // Send token ID to server
                fetch('/create_charge', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        token_id: tokenId,
                        amount: 100, // $1 in cents
                        request_id: requestId
                    })
                })
                .then(function(response) {
                    return response.json();
                })
                .then(function(data) {
                    if (data.processing) {
                        // إذا كانت المعالجة لا تزال جارية، تحقق مرة أخرى بعد ثانية
                        setTimeout(function() {
                            checkPaymentStatus(requestId);
                        }, 1000);
                    } else {
                        // عرض النتيجة النهائية
                        showPaymentResult(data);
                    }
                })
                .catch(function(error) {
                    document.getElementById('processing').style.display = 'none';
                    document.getElementById('error-message').textContent = 'Network error: ' + error;
                    document.getElementById('error-message').style.display = 'block';
                    document.getElementById('success-message').style.display = 'none';
                    document.querySelector('button').disabled = false;
                });
            }
            
            function checkPaymentStatus(requestId) {
                // التحقق من حالة الدفع
                fetch('/check_status?request_id=' + requestId)
                .then(function(response) {
                    return response.json();
                })
                .then(function(data) {
                    if (data.processing) {
                        // إذا كانت المعالجة لا تزال جارية، تحقق مرة أخرى بعد ثانية
                        setTimeout(function() {
                            checkPaymentStatus(requestId);
                        }, 1000);
                    } else {
                        // عرض النتيجة النهائية
                        showPaymentResult(data);
                    }
                })
                .catch(function(error) {
                    document.getElementById('processing').style.display = 'none';
                    document.getElementById('error-message').textContent = 'Network error: ' + error;
                    document.getElementById('error-message').style.display = 'block';
                    document.getElementById('success-message').style.display = 'none';
                    document.querySelector('button').disabled = false;
                });
            }
            
            function showPaymentResult(data) {
                document.getElementById('processing').style.display = 'none';
                
                if (data.success) {
                    // Show success message
                    document.getElementById('success-message').textContent = data.message;
                    document.getElementById('success-message').style.display = 'block';
                    document.getElementById('error-message').style.display = 'none';
                    document.getElementById('payment-form').style.display = 'none';
                } else {
                    // Show detailed error message
                    var errorMsg = 'Error: ' + data.message;
                    if (data.code) {
                        errorMsg += ' (Code: ' + data.code + ')';
                    }
                    if (data.decline_code) {
                        errorMsg += ' (Decline code: ' + data.decline_code + ')';
                    }
                    
                    document.getElementById('error-message').textContent = errorMsg;
                    document.getElementById('error-message').style.display = 'block';
                    document.getElementById('success-message').style.display = 'none';
                    document.querySelector('button').disabled = false;
                }
            }
        </script>
    </body>
    </html>
    '''

@app.route('/create_charge', methods=['POST'])
def create_charge():
    try:
        data = request.json
        token_id = data['token_id']
        amount = data['amount']  # amount in cents
        request_id = data.get('request_id', str(uuid.uuid4()))
        
        # بدء المعالجة بشكل غير متزامن
        executor.submit(process_charge_async, token_id, amount, request_id)
        
        # إرجاع رد فوري مع معرف الطلب
        return jsonify({
            'processing': True,
            'request_id': request_id,
            'message': 'Payment is being processed'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Unexpected error: {str(e)}'
        }), 500

@app.route('/check_status', methods=['GET'])
def check_status():
    request_id = request.args.get('request_id')
    if not request_id:
        return jsonify({
            'success': False,
            'message': 'Missing request_id parameter'
        }), 400
    
    with results_lock:
        result = results.get(request_id)
    
    if result:
        return jsonify(result)
    else:
        return jsonify({
            'processing': True,
            'message': 'Payment is still being processed'
        })

if __name__ == '__main__':
    app.run(debug=False, threaded=True, host='0.0.0.0', port=5000)
