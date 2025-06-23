from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils.decorators import method_decorator
from django.views.decorators.clickjacking import xframe_options_exempt
from django.conf import settings
import json
import logging
import time
import os
from datetime import datetime
import traceback
import threading
import requests

logger = logging.getLogger(__name__)

class NgrokMiddleware:
    """Middleware to handle ngrok-specific headers and requests"""
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        # Log ALL incoming requests for debugging
        start_time = time.time()
        request_id = str(int(time.time() * 1000))[-6:]  # Last 6 digits for unique ID
        
        logger.info(f"[{request_id}] Incoming request: {request.method} {request.path}")
        logger.info(f"[{request_id}] Headers: {dict(request.headers)}")
        logger.info(f"[{request_id}] Host: {request.get_host()}")
        
        # Log POST data for Slack commands
        if request.method == 'POST' and '/slack/' in request.path:
            logger.info(f"[{request_id}] POST data: {dict(request.POST)}")
            logger.info(f"[{request_id}] Body (first 500 chars): {request.body.decode('utf-8', errors='ignore')[:500]}")
        
        # Skip ngrok browser warning by adding the header
        if 'ngrok-skip-browser-warning' not in request.headers:
            request.META['HTTP_NGROK_SKIP_BROWSER_WARNING'] = 'true'
        
        # Add request ID to request for tracking
        request.debug_id = request_id
        
        response = self.get_response(request)
        
        # Log response details
        end_time = time.time()
        duration = (end_time - start_time) * 1000  # Convert to milliseconds
        logger.info(f"[{request_id}] Response: {response.status_code} in {duration:.2f}ms")
        
        # Add headers to skip ngrok warnings
        if self.is_ngrok_request(request):
            response['ngrok-skip-browser-warning'] = 'true'
        
        return response
    
    def is_ngrok_request(self, request):
        """Check if request is coming through ngrok"""
        host = request.get_host()
        user_agent = request.headers.get('User-Agent', '')
        
        return (
            '.ngrok.io' in host or 
            '.ngrok-free.app' in host or
            'ngrok' in user_agent.lower()
        )

@xframe_options_exempt
def index(request):
    """Basic view that returns 'Slack bot is running'"""
    # Log request details for debugging
    logger.info(f"[{getattr(request, 'debug_id', 'unknown')}] Index request from: {request.get_host()}")
    
    # Handle ngrok browser warning page
    if 'ngrok-skip-browser-warning' in request.headers:
        logger.info(f"[{getattr(request, 'debug_id', 'unknown')}] Skipping ngrok browser warning")
    
    return HttpResponse("Slack bot is running")

@csrf_exempt
def health(request):
    """Health check endpoint"""
    try:
        # Check basic system health
        health_data = {
            "status": "ok",
            "timestamp": datetime.now().isoformat(),
            "django_debug": settings.DEBUG,
            "environment_variables": {
                "SLACK_BOT_TOKEN": bool(os.getenv('SLACK_BOT_TOKEN')),
                "SLACK_SIGNING_SECRET": bool(os.getenv('SLACK_SIGNING_SECRET')),
                "GEMINI_API_KEY": bool(os.getenv('GEMINI_API_KEY')),
                "DJANGO_SECRET_KEY": bool(os.getenv('DJANGO_SECRET_KEY'))
            }
        }
        
        logger.info(f"[{getattr(request, 'debug_id', 'unknown')}] Health check requested")
        return JsonResponse(health_data)
        
    except Exception as e:
        logger.error(f"[{getattr(request, 'debug_id', 'unknown')}] Health check failed: {str(e)}")
        return JsonResponse({
            "status": "error",
            "timestamp": datetime.now().isoformat(),
            "error": str(e)
        }, status=500)

@csrf_exempt
def slack_test(request):
    """Test endpoint for configuration verification"""
    try:
        request_id = getattr(request, 'debug_id', 'unknown')
        logger.info(f"[{request_id}] Test endpoint accessed")
        
        # Check environment variables
        env_status = {}
        required_vars = ['SLACK_BOT_TOKEN', 'SLACK_SIGNING_SECRET', 'GEMINI_API_KEY', 'DJANGO_SECRET_KEY']
        
        for var in required_vars:
            value = os.getenv(var)
            if not value:
                env_status[var] = "❌ Missing"
            elif value.startswith('your-'):
                env_status[var] = "⚠️ Default template value"
            else:
                env_status[var] = "✅ Set"
        
        # Check services
        try:
            from .services.slack_service import SlackService
            slack_service = SlackService()
            slack_status = "✅ Service initialized"
        except Exception as e:
            slack_status = f"❌ Error: {str(e)}"
        
        try:
            from .services.gemini_service import GeminiService
            gemini_service = GeminiService()
            gemini_status = "✅ Service initialized"
        except Exception as e:
            gemini_status = f"❌ Error: {str(e)}"
        
        test_data = {
            "status": "Test endpoint working",
            "timestamp": datetime.now().isoformat(),
            "request_method": request.method,
            "host": request.get_host(),
            "is_ngrok": 'ngrok' in request.get_host(),
            "debug_mode": settings.DEBUG,
            "environment_variables": env_status,
            "services": {
                "slack_service": slack_status,
                "gemini_service": gemini_status
            },
            "endpoints": {
                "health": f"http://{request.get_host()}/health/",
                "slack_commands": f"http://{request.get_host()}/slack/commands/",
                "slack_events": f"http://{request.get_host()}/slack/events/"
            }
        }
        
        return JsonResponse(test_data, json_dumps_params={'indent': 2})
        
    except Exception as e:
        logger.error(f"[{getattr(request, 'debug_id', 'unknown')}] Test endpoint error: {str(e)}")
        return JsonResponse({
            "status": "error",
            "timestamp": datetime.now().isoformat(),
            "error": str(e),
            "traceback": traceback.format_exc() if settings.DEBUG else None
        }, status=500)

@csrf_exempt
@require_http_methods(["POST"])
def slack_events(request):
    """Handle Slack events and interactions"""
    request_id = getattr(request, 'debug_id', 'unknown')
    
    try:
        logger.info(f"[{request_id}] Processing Slack event")
        
        # Parse the JSON payload
        data = json.loads(request.body.decode('utf-8'))
        logger.info(f"[{request_id}] Event data: {data}")
        
        # Handle URL verification challenge
        if data.get('type') == 'url_verification':
            challenge = data.get('challenge')
            logger.info(f"[{request_id}] URL verification challenge: {challenge}")
            return JsonResponse({'challenge': challenge})
        
        # Handle event callbacks
        if data.get('type') == 'event_callback':
            event = data.get('event', {})
            logger.info(f"[{request_id}] Received event: {event.get('type')}")
            
            # Process the event here
            # You can add your event handling logic here
            
        return JsonResponse({'status': 'ok'})
        
    except json.JSONDecodeError as e:
        logger.error(f"[{request_id}] Invalid JSON payload: {str(e)}")
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"[{request_id}] Error processing Slack event: {str(e)}", exc_info=True)
        return JsonResponse({'error': 'Internal server error'}, status=500)

@csrf_exempt
@require_http_methods(["POST"])
def slack_commands(request):
    """Handle Slack slash commands with full AI-powered summaries"""
    request_id = getattr(request, 'debug_id', 'unknown')
    start_time = time.time()
    
    try:
        logger.info(f"[{request_id}] ⚡ Starting slash command processing")
        
        # Slack sends form data for slash commands, not JSON
        command = request.POST.get('command', '')
        text = request.POST.get('text', '')
        user_id = request.POST.get('user_id', '')
        user_name = request.POST.get('user_name', '')
        channel_id = request.POST.get('channel_id', '')
        team_id = request.POST.get('team_id', '')
        response_url = request.POST.get('response_url', '')
        
        # Enhanced logging
        logger.info(f"[{request_id}] 📝 Command details:")
        logger.info(f"[{request_id}]   Command: {command}")
        logger.info(f"[{request_id}]   Text: '{text}'")
        logger.info(f"[{request_id}]   User: {user_name} ({user_id})")
        logger.info(f"[{request_id}]   Channel: {channel_id}")
        logger.info(f"[{request_id}]   Team: {team_id}")
        
        # Check for signature validation bypass in debug mode
        if settings.DEBUG:
            logger.warning(f"[{request_id}] ⚠️ DEBUG MODE: Slack signature validation bypassed")
        
        # Handle different slash commands
        if command == '/summary':
            logger.info(f"[{request_id}] 🔄 Processing summary command with full AI capabilities")
            
            # Quick timeout check - if we're approaching 2.5 seconds, return fast response
            elapsed = time.time() - start_time
            if elapsed > 2.5:
                logger.warning(f"[{request_id}] ⏰ Approaching timeout ({elapsed:.2f}s), returning quick summary")
                channel_name = parse_channel_name(text) or 'current channel'
                return JsonResponse({
                    'response_type': 'ephemeral',
                    'text': f'⚡ **Quick Response** (timeout protection)\n\n' +
                           f'✅ Bot is working with full permissions!\n' +
                           f'📝 Requested: Summary for #{channel_name}\n' +
                           f'⏰ Processing took too long, but OAuth scopes are now configured correctly.\n\n' +
                           f'🔄 Try the command again - it should work faster now!'
                })
            
            # Process the full summary with AI
            response = handle_summary_command(text, user_name, request_id)
            
            end_time = time.time()
            duration = (end_time - start_time) * 1000
            logger.info(f"[{request_id}] ✅ Summary command completed in {duration:.2f}ms")
            
            return response
            
        else:
            # Unknown command
            logger.warning(f"[{request_id}] ❓ Unknown command received: {command}")
            return JsonResponse({
                'response_type': 'ephemeral',
                'text': f'❌ Unknown command: {command}\n\n' +
                       f'Available commands:\n' +
                       f'• `/summary #channel-name` - Get AI-powered channel summary'
            })
        
    except Exception as e:
        end_time = time.time()
        duration = (end_time - start_time) * 1000
        
        logger.error(f"[{request_id}] ❌ Error processing Slack command after {duration:.2f}ms: {str(e)}", exc_info=True)
        
        # Always return a valid response to Slack, even on error
        return JsonResponse({
            'response_type': 'ephemeral',
            'text': f'❌ Sorry, there was an error processing your command.\n\n' +
                   f'**Error details:** {str(e)[:200]}...\n' +
                   f'**Duration:** {duration:.1f}ms\n\n' +
                   f'Please try again in a few moments.'
        })

@csrf_exempt
@require_http_methods(["POST"])
def slack_commands_fast(request):
    """Fast slash command handler that works with limited permissions"""
    request_id = getattr(request, 'debug_id', 'unknown')
    
    try:
        command = request.POST.get('command', '')
        text = request.POST.get('text', '')
        user_name = request.POST.get('user_name', '')
        channel_id = request.POST.get('channel_id', '')
        
        logger.info(f"[{request_id}] 🚀 Fast command: {command} in {channel_id}")
        
        if command == '/summary':
            channel_name = parse_channel_name(text) or 'current channel'
            
            # Return immediate helpful response without trying to access restricted APIs
            return JsonResponse({
                'response_type': 'ephemeral',
                'text': f'🤖 **Beta-Summarizer Bot Status**\n\n' +
                       f'✅ **Bot is working!** Command received from @{user_name}\n' +
                       f'📝 **Requested:** Summary for #{channel_name}\n\n' +
                       f'⚠️ **Current Issue:** Missing OAuth permissions\n' +
                       f'🔧 **Quick Fix:** Add these scopes to your Slack app:\n\n' +
                       f'**Required OAuth Scopes:**\n' +
                       f'• `channels:read` - List and view channels\n' +
                       f'• `channels:history` - Read channel messages  \n' +
                       f'• `users:read` - Get user names\n' +
                       f'• `chat:write` - Send responses\n\n' +
                       f'**How to fix:**\n' +
                       f'1. Go to https://api.slack.com/apps\n' +
                       f'2. Select your app → OAuth & Permissions\n' +
                       f'3. Add the scopes above\n' +
                       f'4. Reinstall the app to your workspace\n\n' +
                       f'✨ **Once fixed, I\'ll provide full AI-powered summaries!**'
            })
        
        return JsonResponse({
            'response_type': 'ephemeral',
            'text': f'❓ Unknown command: {command}'
        })
        
    except Exception as e:
        logger.error(f"[{request_id}] Fast command error: {str(e)}")
        return JsonResponse({
            'response_type': 'ephemeral',
            'text': '✅ Bot is running, but needs proper OAuth permissions to function fully.'
        })

@csrf_exempt
@require_http_methods(["POST"])
def slack_commands_ultra_fast(request):
    """Ultra-fast slash command handler that responds instantly and processes asynchronously"""
    request_id = getattr(request, 'debug_id', 'unknown')
    start_time = time.time()
    
    try:
        command = request.POST.get('command', '')
        text = request.POST.get('text', '').strip()
        user_name = request.POST.get('user_name', '')
        user_id = request.POST.get('user_id', '')
        channel_id = request.POST.get('channel_id', '')
        response_url = request.POST.get('response_url', '')
        
        logger.info(f"[{request_id}] ⚡ Ultra-fast command: {command} with text: '{text}'")
        
        # Check if this is an unread request
        is_unread_request = (
            'unread' in text.lower() or 
            command == '/unread' or
            text.lower().startswith('unread ')
        )
        
        if command == '/summary' or command == '/unread' or is_unread_request:
            # Parse the actual channel name (remove "unread" prefix if present)
            if is_unread_request and text.lower().startswith('unread '):
                actual_text = text[6:].strip()  # Remove "unread " prefix
            elif command == '/unread':
                actual_text = text
            else:
                actual_text = text
            
            channel_name = parse_channel_name(actual_text) or 'specified channel'
            
            if is_unread_request or command == '/unread':
                # Handle unread messages request
                logger.info(f"[{request_id}] 📬 Processing unread request for #{channel_name}")
                
                # Start background processing for unread messages
                def background_unread_process():
                    try:
                        logger.info(f"[{request_id}] 🔄 Starting background unread analysis for #{channel_name}")
                        
                        # Generate the unread summary
                        unread_response = handle_unread_summary_command(actual_text, user_name, user_id, f"{request_id}-unread")
                        
                        if hasattr(unread_response, 'content'):
                            import json
                            unread_data = json.loads(unread_response.content.decode('utf-8'))
                            unread_text = unread_data.get('text', 'Unread summary completed.')
                            
                            # Post the unread summary back to Slack using response_url
                            if response_url:
                                followup_payload = {
                                    'response_type': 'ephemeral',  # Only visible to the requesting user
                                    'text': unread_text,
                                    'replace_original': True
                                }
                                
                                try:
                                    followup_response = requests.post(
                                        response_url, 
                                        json=followup_payload,
                                        timeout=10
                                    )
                                    if followup_response.status_code == 200:
                                        logger.info(f"[{request_id}] ✅ Unread summary posted successfully")
                                    else:
                                        logger.error(f"[{request_id}] ❌ Failed to post unread summary: {followup_response.status_code}")
                                except Exception as e:
                                    logger.error(f"[{request_id}] ❌ Error posting unread summary: {str(e)}")
                        
                    except Exception as e:
                        logger.error(f"[{request_id}] ❌ Background unread processing error: {str(e)}")
                        
                        # Send error message back to user
                        if response_url:
                            error_payload = {
                                'response_type': 'ephemeral',
                                'text': f'❌ Sorry, there was an error generating your unread summary for #{channel_name}.\n\n' +
                                       f'Please try again in a few moments.\n' +
                                       f'Error: {str(e)[:100]}...',
                                'replace_original': True
                            }
                            try:
                                requests.post(response_url, json=error_payload, timeout=5)
                            except:
                                pass
                
                # Start background thread
                background_thread = threading.Thread(target=background_unread_process)
                background_thread.daemon = True
                background_thread.start()
                
                # IMMEDIATE response to Slack for unread request
                response = JsonResponse({
                    'response_type': 'ephemeral',
                    'text': f'📬 **Checking unread messages for #{channel_name}...**\n\n' +
                           f'🔍 AI analyzing messages you haven\'t seen yet.\n' +
                           f'⚡ Personalized catch-up summary generating now.\n' +
                           f'⏱️ This usually takes 5-15 seconds.\n\n' +
                           f'📋 **Your personalized unread summary will appear shortly!**'
                })
                
            else:
                # Handle regular summary request
                logger.info(f"[{request_id}] 📊 Processing regular summary for #{channel_name}")
                
                # Start background processing immediately
                def background_process():
                    try:
                        logger.info(f"[{request_id}] 🔄 Starting background AI summary for #{channel_name}")
                        
                        # Generate the actual summary using dedicated background function (no timeout protection)
                        summary_response = handle_summary_command_background(text, user_name, f"{request_id}-bg")
                        
                        if hasattr(summary_response, 'content'):
                            import json
                            summary_data = json.loads(summary_response.content.decode('utf-8'))
                            summary_text = summary_data.get('text', 'Summary generation completed.')
                            
                            # Post the actual summary back to Slack using response_url
                            if response_url:
                                followup_payload = {
                                    'response_type': 'in_channel',  # Make it visible to everyone
                                    'text': summary_text,
                                    'replace_original': True  # Replace the "Processing..." message
                                }
                                
                                try:
                                    followup_response = requests.post(
                                        response_url, 
                                        json=followup_payload,
                                        timeout=10
                                    )
                                    if followup_response.status_code == 200:
                                        logger.info(f"[{request_id}] ✅ AI summary posted successfully")
                                    else:
                                        logger.error(f"[{request_id}] ❌ Failed to post summary: {followup_response.status_code}")
                                except Exception as e:
                                    logger.error(f"[{request_id}] ❌ Error posting summary: {str(e)}")
                            else:
                                logger.warning(f"[{request_id}] ⚠️ No response_url provided for followup")
                        
                    except Exception as e:
                        logger.error(f"[{request_id}] ❌ Background processing error: {str(e)}")
                        
                        # Send error message back to user
                        if response_url:
                            error_payload = {
                                'response_type': 'ephemeral',
                                'text': f'❌ Sorry, there was an error generating the summary for #{channel_name}.\n\n' +
                                       f'Please try again in a few moments.\n' +
                                       f'Error: {str(e)[:100]}...',
                                'replace_original': True
                            }
                            try:
                                requests.post(response_url, json=error_payload, timeout=5)
                            except:
                                pass
                
                # Start background thread
                background_thread = threading.Thread(target=background_process)
                background_thread.daemon = True
                background_thread.start()
                
                # IMMEDIATE response to Slack (< 100ms)
                response = JsonResponse({
                    'response_type': 'ephemeral',
                    'text': f'⚡ **Processing summary for #{channel_name}...**\n\n' +
                           f'🤖 AI analysis starting now with full OAuth permissions.\n' +
                           f'📊 Fetching messages and generating intelligent summary.\n' +
                           f'⏱️ This usually takes 10-30 seconds for detailed analysis.\n\n' +
                           f'✨ **Full AI-powered summary will appear shortly!**'
                })
            
            elapsed = (time.time() - start_time) * 1000
            logger.info(f"[{request_id}] ⚡ Ultra-fast response sent in {elapsed:.1f}ms, background processing started")
            
            return response
        
        return JsonResponse({
            'response_type': 'ephemeral',
            'text': f'❓ Unknown command: {command}'
        })
        
    except Exception as e:
        elapsed = (time.time() - start_time) * 1000
        logger.error(f"[{request_id}] Ultra-fast command error after {elapsed:.1f}ms: {str(e)}")
        return JsonResponse({
            'response_type': 'ephemeral',
            'text': '❌ Error processing your request. Please try again.'
        })

def handle_summary_command(text, user_name, request_id):
    """Handle the /summary command workflow with comprehensive error handling"""
    from .services.slack_service import SlackService
    from .services.gemini_service import GeminiService
    
    # Track overall start time for timeout protection
    start_time = time.time()
    step_start = time.time()
    
    try:
        logger.info(f"[{request_id}] 🔍 Step 1: Parsing channel name")
        
        # Parse channel name from command text
        channel_name = parse_channel_name(text)
        logger.info(f"[{request_id}] Parsed channel name: '{channel_name}'")
        
        if not channel_name:
            logger.info(f"[{request_id}] ❌ No channel name provided")
            return JsonResponse({
                'response_type': 'ephemeral',
                'text': '📝 Please specify a channel to summarize.\n\n' +
                       'Usage: `/summary #channel-name`\n' +
                       'Examples:\n' +
                       '• `/summary #general`\n' +
                       '• `/summary general`\n' +
                       '• `/summary #random`'
            })
        
        step_duration = (time.time() - step_start) * 1000
        logger.info(f"[{request_id}] ✅ Step 1 completed in {step_duration:.2f}ms")
        
        # Step 2: Initialize services
        step_start = time.time()
        logger.info(f"[{request_id}] 🔧 Step 2: Initializing services")
        
        try:
            slack_service = SlackService()
            gemini_service = GeminiService()
            step_duration = (time.time() - step_start) * 1000
            logger.info(f"[{request_id}] ✅ Step 2 completed in {step_duration:.2f}ms")
        except Exception as e:
            logger.error(f"[{request_id}] ❌ Step 2 failed: Service initialization error: {str(e)}", exc_info=True)
            return JsonResponse({
                'response_type': 'ephemeral',
                'text': f"❌ Service initialization failed. Please contact administrator.\nError: {str(e)[:100]}"
            })
        
        # Step 3: Find channel ID
        step_start = time.time()
        logger.info(f"[{request_id}] 🔍 Step 3: Looking up channel ID for: {channel_name}")
        
        try:
            channel_id = slack_service.find_channel_id(channel_name)
            step_duration = (time.time() - step_start) * 1000
            logger.info(f"[{request_id}] ✅ Step 3 completed in {step_duration:.2f}ms")
        except Exception as e:
            logger.error(f"[{request_id}] ❌ Step 3 failed: Channel lookup error: {str(e)}", exc_info=True)
            return JsonResponse({
                'response_type': 'ephemeral',
                'text': f"❌ Failed to lookup channel #{channel_name}.\n\nThis might be due to:\n" +
                       "• Network connectivity issues\n" +
                       "• Invalid Slack API token\n" +
                       "• SSL certificate issues\n\n" +
                       f"Technical error: {str(e)[:100]}"
            })
        
        if not channel_id:
            logger.info(f"[{request_id}] ❌ Channel not found: {channel_name}")
            return JsonResponse({
                'response_type': 'ephemeral',
                'text': f"❌ I couldn't find the channel #{channel_name}.\n\n" +
                       "Please make sure:\n" +
                       "• The channel name is spelled correctly\n" +
                       "• The channel exists and is accessible\n" +
                       "• You have permission to view the channel"
            })
        
        logger.info(f"[{request_id}] Found channel ID: {channel_id}")
        
        # Step 4: Check bot membership
        step_start = time.time()
        logger.info(f"[{request_id}] 👤 Step 4: Checking bot membership in channel {channel_id}")
        
        try:
            is_member = slack_service.check_bot_membership(channel_id)
            step_duration = (time.time() - step_start) * 1000
            logger.info(f"[{request_id}] ✅ Step 4 completed in {step_duration:.2f}ms")
        except Exception as e:
            logger.error(f"[{request_id}] ❌ Step 4 failed: Membership check error: {str(e)}", exc_info=True)
            return JsonResponse({
                'response_type': 'ephemeral',
                'text': f"❌ Failed to check bot membership in #{channel_name}.\n\n" +
                       f"Technical error: {str(e)[:100]}"
            })
        
        if not is_member:
            logger.info(f"[{request_id}] ❌ Bot not a member of channel {channel_id}")
            return JsonResponse({
                'response_type': 'ephemeral',
                'text': f"❌ I need to be added to #{channel_name} first.\n\n" +
                       f"Please type `/invite @Beta-Summarizer` in #{channel_name}, " +
                       "then try the summary command again."
            })
        
        logger.info(f"[{request_id}] Bot is a member of channel {channel_id}")
        
        # Step 5: Fetch messages
        step_start = time.time()
        logger.info(f"[{request_id}] 📥 Step 5: Fetching messages from channel {channel_id}")
        
        try:
            messages = slack_service.fetch_channel_messages(channel_id, hours_back=24)
            step_duration = (time.time() - step_start) * 1000
            logger.info(f"[{request_id}] ✅ Step 5 completed in {step_duration:.2f}ms")
        except Exception as e:
            logger.error(f"[{request_id}] ❌ Step 5 failed: Message fetch error: {str(e)}", exc_info=True)
            return JsonResponse({
                'response_type': 'ephemeral',
                'text': f"❌ Failed to fetch messages from #{channel_name}.\n\n" +
                       f"Technical error: {str(e)[:100]}"
            })
        
        if not messages:
            logger.info(f"[{request_id}] 📭 No messages found in channel {channel_id}")
            return JsonResponse({
                'response_type': 'ephemeral',
                'text': f"📭 No messages found in #{channel_name} in the last 24 hours.\n\n" +
                       "The channel appears to be quiet recently. " +
                       "Try again when there's more activity!"
            })
        
        logger.info(f"[{request_id}] Fetched {len(messages)} messages")
        
        # Step 6: Enrich messages
        step_start = time.time()
        logger.info(f"[{request_id}] 👥 Step 6: Enriching messages with user information")
        
        try:
            enriched_messages = slack_service.enrich_messages_with_usernames(messages)
            step_duration = (time.time() - step_start) * 1000
            logger.info(f"[{request_id}] ✅ Step 6 completed in {step_duration:.2f}ms")
        except Exception as e:
            logger.error(f"[{request_id}] ❌ Step 6 failed: Message enrichment error: {str(e)}", exc_info=True)
            return JsonResponse({
                'response_type': 'ephemeral',
                'text': f"❌ Failed to enrich messages with user information.\n\n" +
                       f"Technical error: {str(e)[:100]}"
            })
        
        if not enriched_messages:
            logger.info(f"[{request_id}] 📭 No valid messages after enrichment")
            return JsonResponse({
                'response_type': 'ephemeral',
                'text': f"📭 No valid messages found in #{channel_name} to summarize.\n\n" +
                       "The messages might be from bots or have other issues."
            })
        
        logger.info(f"[{request_id}] Enriched {len(enriched_messages)} messages with usernames")
        
        # Step 7: Generate summary with timeout protection
        step_start = time.time()
        logger.info(f"[{request_id}] 🤖 Step 7: Generating summary for {len(enriched_messages)} messages")
        
        # Check if we're approaching the 3-second Slack timeout
        total_elapsed = time.time() - start_time
        if total_elapsed > 2.5:  # 2.5 seconds safety margin
            logger.warning(f"[{request_id}] ⏰ Approaching timeout ({total_elapsed:.2f}s), returning quick summary")
            summary = f"📊 **Quick Summary for #{channel_name}**\n\n" + \
                     f"✅ Found {len(enriched_messages)} messages from {len(set(msg['username'] for msg in enriched_messages))} users in the last 24 hours.\n\n" + \
                     f"📝 Processing time exceeded limit for detailed AI analysis.\n" + \
                     f"💡 Try again for a detailed summary, or check a smaller/less active channel."
        else:
            try:
                summary = gemini_service.summarize_messages(enriched_messages, channel_name)
                step_duration = (time.time() - step_start) * 1000
                logger.info(f"[{request_id}] ✅ Step 7 completed in {step_duration:.2f}ms")
            except Exception as e:
                logger.error(f"[{request_id}] ❌ Step 7 failed: Summary generation error: {str(e)}", exc_info=True)
                # Generate a fallback summary
                summary = f"📊 **Summary for #{channel_name}**\n\n" + \
                         f"Found {len(enriched_messages)} messages in the last 24 hours, " + \
                         f"but AI summarization is currently unavailable.\n\n" + \
                         f"*Error: {str(e)[:100]}*"
        
        logger.info(f"[{request_id}] 🎉 Summary generated successfully")
        
        # Return the formatted summary
        return JsonResponse({
            'response_type': 'in_channel',
            'text': summary
        })
        
    except Exception as e:
        logger.error(f"[{request_id}] ❌ CRITICAL ERROR in handle_summary_command: {str(e)}", exc_info=True)
        
        # Always return a valid response to Slack
        return JsonResponse({
            'response_type': 'ephemeral',
            'text': f"❌ Sorry, there was an unexpected error generating the summary.\n\n" +
                   f"Please try again in a few moments. If the problem persists, " +
                   f"contact your workspace administrator.\n\n" +
                   f"Error reference: {request_id}"
        })

def handle_summary_command_background(text, user_name, request_id):
    """Handle summary command in background without timeout protection for full AI processing"""
    from .services.slack_service import SlackService
    from .services.gemini_service import GeminiService
    
    start_time = time.time()
    
    try:
        logger.info(f"[{request_id}] 🔄 Background processing: Parsing channel name")
        
        channel_name = parse_channel_name(text)
        if not channel_name:
            return JsonResponse({
                'response_type': 'ephemeral',
                'text': '📝 Please specify a channel to summarize.'
            })
        
        logger.info(f"[{request_id}] 🔧 Background processing: Initializing services")
        slack_service = SlackService()
        gemini_service = GeminiService()
        
        logger.info(f"[{request_id}] 🔍 Background processing: Looking up channel ID for: {channel_name}")
        channel_id = slack_service.find_channel_id(channel_name)
        
        if not channel_id:
            return JsonResponse({
                'response_type': 'ephemeral',
                'text': f"❌ I couldn't find the channel #{channel_name}."
            })
        
        logger.info(f"[{request_id}] 👤 Background processing: Checking bot membership")
        is_member = slack_service.check_bot_membership(channel_id)
        
        if not is_member:
            return JsonResponse({
                'response_type': 'ephemeral',
                'text': f"❌ I need to be added to #{channel_name} first."
            })
        
        logger.info(f"[{request_id}] 📥 Background processing: Fetching messages")
        messages = slack_service.fetch_channel_messages(channel_id, hours_back=24)
        
        if not messages:
            return JsonResponse({
                'response_type': 'in_channel',
                'text': f"📭 No messages found in #{channel_name} in the last 24 hours."
            })
        
        logger.info(f"[{request_id}] 👥 Background processing: Enriching {len(messages)} messages")
        enriched_messages = slack_service.enrich_messages_with_usernames(messages)
        
        if not enriched_messages:
            return JsonResponse({
                'response_type': 'in_channel',
                'text': f"📭 No valid messages found in #{channel_name} to summarize."
            })
        
        logger.info(f"[{request_id}] 🤖 Background processing: Generating AI summary for {len(enriched_messages)} messages")
        
        # NO TIMEOUT PROTECTION HERE - let it run as long as needed
        summary = gemini_service.summarize_messages(enriched_messages, channel_name)
        
        total_elapsed = time.time() - start_time
        logger.info(f"[{request_id}] ✅ Background processing completed in {total_elapsed:.2f}s")
        
        return JsonResponse({
            'response_type': 'in_channel',
            'text': summary
        })
        
    except Exception as e:
        total_elapsed = time.time() - start_time
        logger.error(f"[{request_id}] ❌ Background processing error after {total_elapsed:.2f}s: {str(e)}", exc_info=True)
        
        return JsonResponse({
            'response_type': 'ephemeral',
            'text': f"❌ Sorry, there was an error generating the summary.\n\nError: {str(e)[:100]}..."
        })

def parse_channel_name(text):
    """Parse channel name from command text, handling various formats"""
    if not text:
        return None
    
    # Clean up the text
    text = text.strip()
    
    # Handle formats: "#general", "general", or just whitespace
    if text.startswith('#'):
        channel_name = text[1:].strip()
    else:
        channel_name = text.strip()
    
    # Return None if empty after processing
    return channel_name if channel_name else None

def handle_unread_summary_command(text, user_name, user_id, request_id):
    """Handle the /unread command workflow to summarize only unread messages"""
    from .services.slack_service import SlackService
    from .services.gemini_service import GeminiService
    
    # Track overall start time for timeout protection
    start_time = time.time()
    step_start = time.time()
    
    try:
        logger.info(f"[{request_id}] 🔍 Unread Step 1: Parsing channel name")
        
        # Parse channel name from command text
        channel_name = parse_channel_name(text)
        logger.info(f"[{request_id}] Parsed channel name: '{channel_name}'")
        
        if not channel_name:
            logger.info(f"[{request_id}] ❌ No channel name provided for unread summary")
            return JsonResponse({
                'response_type': 'ephemeral',
                'text': '📬 Please specify a channel to check for unread messages.\n\n' +
                       'Usage: `/unread #channel-name`\n' +
                       'Examples:\n' +
                       '• `/unread #general`\n' +
                       '• `/unread general`\n' +
                       '• `/unread #team-updates`'
            })
        
        step_duration = (time.time() - step_start) * 1000
        logger.info(f"[{request_id}] ✅ Unread Step 1 completed in {step_duration:.2f}ms")
        
        # Step 2: Initialize services
        step_start = time.time()
        logger.info(f"[{request_id}] 🔧 Unread Step 2: Initializing services")
        
        try:
            slack_service = SlackService()
            gemini_service = GeminiService()
            step_duration = (time.time() - step_start) * 1000
            logger.info(f"[{request_id}] ✅ Unread Step 2 completed in {step_duration:.2f}ms")
        except Exception as e:
            logger.error(f"[{request_id}] ❌ Unread Step 2 failed: Service initialization error: {str(e)}", exc_info=True)
            return JsonResponse({
                'response_type': 'ephemeral',
                'text': f"❌ Service initialization failed. Please contact administrator.\nError: {str(e)[:100]}"
            })
        
        # Step 3: Find channel ID
        step_start = time.time()
        logger.info(f"[{request_id}] 🔍 Unread Step 3: Looking up channel ID for: {channel_name}")
        
        try:
            channel_id = slack_service.find_channel_id(channel_name)
            step_duration = (time.time() - step_start) * 1000
            logger.info(f"[{request_id}] ✅ Unread Step 3 completed in {step_duration:.2f}ms")
        except Exception as e:
            logger.error(f"[{request_id}] ❌ Unread Step 3 failed: Channel lookup error: {str(e)}", exc_info=True)
            return JsonResponse({
                'response_type': 'ephemeral',
                'text': f"❌ Failed to lookup channel #{channel_name}.\n\nTechnical error: {str(e)[:100]}"
            })
        
        if not channel_id:
            logger.info(f"[{request_id}] ❌ Channel not found: {channel_name}")
            return JsonResponse({
                'response_type': 'ephemeral',
                'text': f"❌ I couldn't find the channel #{channel_name}.\n\n" +
                       "Please make sure:\n" +
                       "• The channel name is spelled correctly\n" +
                       "• The channel exists and is accessible\n" +
                       "• You have permission to view the channel"
            })
        
        logger.info(f"[{request_id}] Found channel ID: {channel_id}")
        
        # Step 4: Check bot membership
        step_start = time.time()
        logger.info(f"[{request_id}] 👤 Unread Step 4: Checking bot membership in channel {channel_id}")
        
        try:
            is_member = slack_service.check_bot_membership(channel_id)
            step_duration = (time.time() - step_start) * 1000
            logger.info(f"[{request_id}] ✅ Unread Step 4 completed in {step_duration:.2f}ms")
        except Exception as e:
            logger.error(f"[{request_id}] ❌ Unread Step 4 failed: Membership check error: {str(e)}", exc_info=True)
            return JsonResponse({
                'response_type': 'ephemeral',
                'text': f"❌ Failed to check bot membership in #{channel_name}.\n\nTechnical error: {str(e)[:100]}"
            })
        
        if not is_member:
            logger.info(f"[{request_id}] ❌ Bot not a member of channel {channel_id}")
            return JsonResponse({
                'response_type': 'ephemeral',
                'text': f"❌ I need to be added to #{channel_name} first.\n\n" +
                       f"Please type `/invite @Beta-Summarizer` in #{channel_name}, " +
                       "then try the unread command again."
            })
        
        logger.info(f"[{request_id}] Bot is a member of channel {channel_id}")
        
        # Step 5: Fetch unread messages
        step_start = time.time()
        logger.info(f"[{request_id}] 📥 Unread Step 5: Fetching unread messages from channel {channel_id} for user {user_id}")
        
        try:
            messages = slack_service.fetch_unread_messages(channel_id, user_id)
            step_duration = (time.time() - step_start) * 1000
            logger.info(f"[{request_id}] ✅ Unread Step 5 completed in {step_duration:.2f}ms")
        except Exception as e:
            logger.error(f"[{request_id}] ❌ Unread Step 5 failed: Unread message fetch error: {str(e)}", exc_info=True)
            return JsonResponse({
                'response_type': 'ephemeral',
                'text': f"❌ Failed to fetch unread messages from #{channel_name}.\n\nTechnical error: {str(e)[:100]}"
            })
        
        if not messages:
            logger.info(f"[{request_id}] 📭 No unread messages found in channel {channel_id}")
            return JsonResponse({
                'response_type': 'ephemeral',
                'text': f"📬 Great news! You have no unread messages in #{channel_name}.\n\n" +
                       "🎉 You're all caught up with recent activity!\n\n" +
                       "💡 If you expect unread messages, they might be older than 2 hours."
            })
        
        logger.info(f"[{request_id}] Fetched {len(messages)} unread messages")
        
        # Step 6: Enrich messages
        step_start = time.time()
        logger.info(f"[{request_id}] 👥 Unread Step 6: Enriching unread messages with user information")
        
        try:
            enriched_messages = slack_service.enrich_messages_with_usernames(messages)
            step_duration = (time.time() - step_start) * 1000
            logger.info(f"[{request_id}] ✅ Unread Step 6 completed in {step_duration:.2f}ms")
        except Exception as e:
            logger.error(f"[{request_id}] ❌ Unread Step 6 failed: Message enrichment error: {str(e)}", exc_info=True)
            return JsonResponse({
                'response_type': 'ephemeral',
                'text': f"❌ Failed to enrich unread messages with user information.\n\nTechnical error: {str(e)[:100]}"
            })
        
        if not enriched_messages:
            logger.info(f"[{request_id}] 📭 No valid unread messages after enrichment")
            return JsonResponse({
                'response_type': 'ephemeral',
                'text': f"📬 No valid unread messages found in #{channel_name}.\n\n" +
                       "You're all caught up! 🎉"
            })
        
        logger.info(f"[{request_id}] Enriched {len(enriched_messages)} unread messages with usernames")
        
        # Step 7: Generate unread summary with timeout protection
        step_start = time.time()
        logger.info(f"[{request_id}] 🤖 Unread Step 7: Generating unread summary for {len(enriched_messages)} messages")
        
        # Check if we're approaching the 3-second Slack timeout
        total_elapsed = time.time() - start_time
        if total_elapsed > 2.5:  # 2.5 seconds safety margin
            logger.warning(f"[{request_id}] ⏰ Approaching timeout ({total_elapsed:.2f}s), returning quick unread summary")
            summary = f"📬 **Quick Unread Summary for #{channel_name}**\n\n" + \
                     f"✅ Found {len(enriched_messages)} unread messages from {len(set(msg['username'] for msg in enriched_messages))} users.\n\n" + \
                     f"📝 Processing time exceeded limit for detailed AI analysis.\n" + \
                     f"💡 Try again for a detailed unread summary."
        else:
            try:
                summary = gemini_service.summarize_unread_messages(enriched_messages, channel_name, user_name)
                step_duration = (time.time() - step_start) * 1000
                logger.info(f"[{request_id}] ✅ Unread Step 7 completed in {step_duration:.2f}ms")
            except Exception as e:
                logger.error(f"[{request_id}] ❌ Unread Step 7 failed: Unread summary generation error: {str(e)}", exc_info=True)
                # Generate a fallback summary
                summary = f"📬 **Unread Summary for #{channel_name}**\n\n" + \
                         f"Found {len(enriched_messages)} unread messages, " + \
                         f"but AI summarization is currently unavailable.\n\n" + \
                         f"*Error: {str(e)[:100]}*"
        
        logger.info(f"[{request_id}] 🎉 Unread summary generated successfully")
        
        # Return the formatted unread summary
        return JsonResponse({
            'response_type': 'ephemeral',  # Only visible to the user who requested it
            'text': summary
        })
        
    except Exception as e:
        logger.error(f"[{request_id}] ❌ CRITICAL ERROR in handle_unread_summary_command: {str(e)}", exc_info=True)
        
        # Always return a valid response to Slack
        return JsonResponse({
            'response_type': 'ephemeral',
            'text': f"❌ Sorry, there was an unexpected error generating your unread summary.\n\n" +
                   f"Please try again in a few moments. If the problem persists, " +
                   f"contact your workspace administrator.\n\n" +
                   f"Error reference: {request_id}"
        }) 