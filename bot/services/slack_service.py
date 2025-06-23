import logging
import time
import ssl
import certifi
from datetime import datetime, timedelta
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

class SlackService:
    """Service class for interacting with Slack API with SSL certificate handling"""
    
    def __init__(self):
        # Configure SSL context for certificate verification
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        
        # In development, we might need to be more lenient with SSL
        if settings.DEBUG:
            logger.warning("DEBUG mode: Using relaxed SSL verification for Slack API")
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
        
        self.client = WebClient(
            token=settings.SLACK_BOT_TOKEN,
            ssl=ssl_context
        )
        self.bot_user_id = None
        
        logger.info("SlackService initialized with SSL context")
    
    def get_bot_user_id(self):
        """Get the bot's user ID"""
        if self.bot_user_id:
            return self.bot_user_id
        
        try:
            logger.info("Fetching bot user ID from Slack API")
            response = self.client.auth_test()
            self.bot_user_id = response['user_id']
            logger.info(f"Bot user ID: {self.bot_user_id}")
            return self.bot_user_id
        except SlackApiError as e:
            logger.error(f"SlackApiError getting bot user ID: {e.response['error']}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error getting bot user ID: {str(e)}", exc_info=True)
            return None
    
    def find_channel_id(self, channel_name):
        """Find channel ID by name, handling various formats"""
        # Clean channel name - remove # if present
        clean_name = channel_name.strip().lstrip('#').lower()
        
        if not clean_name:
            logger.warning("Empty channel name provided")
            return None
        
        # Check cache first
        cache_key = f"channel_id_{clean_name}"
        cached_id = cache.get(cache_key)
        if cached_id:
            logger.info(f"Found cached channel ID for #{clean_name}: {cached_id}")
            return cached_id
        
        try:
            logger.info(f"Searching for channel: #{clean_name}")
            cursor = None
            page_count = 0
            
            while True:
                page_count += 1
                logger.debug(f"Fetching channels page {page_count} (cursor: {cursor[:10] if cursor else 'None'}...)")
                
                response = self.client.conversations_list(
                    cursor=cursor,
                    limit=200,
                    types="public_channel,private_channel"
                )
                
                channels = response.get('channels', [])
                logger.debug(f"Retrieved {len(channels)} channels on page {page_count}")
                
                for channel in channels:
                    if channel['name'].lower() == clean_name:
                        channel_id = channel['id']
                        # Cache for 1 hour
                        cache.set(cache_key, channel_id, 3600)
                        logger.info(f"Found channel #{clean_name}: {channel_id}")
                        return channel_id
                
                cursor = response.get('response_metadata', {}).get('next_cursor')
                if not cursor:
                    break
                    
                # Rate limiting protection
                time.sleep(0.5)
            
            logger.warning(f"Channel #{clean_name} not found after searching {page_count} pages")
            return None
            
        except SlackApiError as e:
            logger.error(f"SlackApiError finding channel #{clean_name}: {e.response['error']}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error finding channel #{clean_name}: {str(e)}", exc_info=True)
            return None
    
    def check_bot_membership(self, channel_id):
        """Check if bot is a member of the channel"""
        try:
            logger.info(f"Checking bot membership in channel: {channel_id}")
            
            bot_user_id = self.get_bot_user_id()
            if not bot_user_id:
                logger.error("Could not get bot user ID for membership check")
                return False
            
            response = self.client.conversations_members(channel=channel_id)
            members = response.get('members', [])
            
            is_member = bot_user_id in members
            logger.info(f"Bot membership in {channel_id}: {is_member} (bot_id: {bot_user_id})")
            return is_member
            
        except SlackApiError as e:
            # If we get a channel_not_found or not_in_channel error, bot is not a member
            if e.response['error'] in ['channel_not_found', 'not_in_channel']:
                logger.info(f"Bot is not a member of channel {channel_id}: {e.response['error']}")
                return False
            logger.error(f"SlackApiError checking bot membership in {channel_id}: {e.response['error']}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error checking bot membership in {channel_id}: {str(e)}", exc_info=True)
            return False
    
    def fetch_channel_messages(self, channel_id, hours_back=24):
        """Fetch messages from a channel within the specified time range"""
        try:
            # Calculate timestamp for messages (24 hours ago)
            oldest_time = datetime.now() - timedelta(hours=hours_back)
            oldest_ts = oldest_time.timestamp()
            
            logger.info(f"Fetching messages from {channel_id} since {oldest_time} (ts: {oldest_ts})")
            
            messages = []
            cursor = None
            page_count = 0
            
            while True:
                page_count += 1
                logger.debug(f"Fetching messages page {page_count} (cursor: {cursor[:10] if cursor else 'None'}...)")
                
                response = self.client.conversations_history(
                    channel=channel_id,
                    oldest=str(oldest_ts),
                    cursor=cursor,
                    limit=200
                )
                
                channel_messages = response.get('messages', [])
                logger.debug(f"Retrieved {len(channel_messages)} raw messages on page {page_count}")
                
                if not channel_messages:
                    break
                
                # Filter out bot messages and system messages
                filtered_count = 0
                for msg in channel_messages:
                    if (msg.get('type') == 'message' and 
                        not msg.get('bot_id') and 
                        msg.get('user') and
                        not msg.get('subtype')):
                        messages.append(msg)
                        filtered_count += 1
                
                logger.debug(f"Filtered to {filtered_count} valid messages on page {page_count}")
                
                cursor = response.get('response_metadata', {}).get('next_cursor')
                if not cursor:
                    break
                    
                # Rate limiting protection
                time.sleep(0.5)
            
            # Sort messages by timestamp (oldest first)
            messages.sort(key=lambda x: float(x['ts']))
            
            logger.info(f"Fetched {len(messages)} messages from {channel_id} across {page_count} pages")
            return messages
            
        except SlackApiError as e:
            logger.error(f"SlackApiError fetching messages from {channel_id}: {e.response['error']}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error fetching messages from {channel_id}: {str(e)}", exc_info=True)
            return []
    
    def enrich_messages_with_usernames(self, messages):
        """Add username information to messages"""
        logger.info(f"Enriching {len(messages)} messages with usernames")
        
        user_cache = {}
        enriched_messages = []
        
        for i, msg in enumerate(messages):
            user_id = msg.get('user')
            if not user_id:
                logger.debug(f"Message {i} has no user_id, skipping")
                continue
                
            # Get username from cache or API
            if user_id not in user_cache:
                try:
                    logger.debug(f"Fetching user info for {user_id}")
                    user_info = self.get_user_info(user_id)
                    username = user_info.get('display_name') or user_info.get('real_name') or user_info.get('name', f'User_{user_id}')
                    user_cache[user_id] = username
                    logger.debug(f"User {user_id} -> {username}")
                    # Small delay to respect rate limits
                    time.sleep(0.1)
                except Exception as e:
                    logger.warning(f"Could not get username for {user_id}: {str(e)}")
                    user_cache[user_id] = f'User_{user_id}'
            
            # Create enriched message
            timestamp = datetime.fromtimestamp(float(msg['ts']))
            enriched_msg = {
                'timestamp': timestamp,
                'username': user_cache[user_id],
                'text': msg.get('text', ''),
                'user_id': user_id,
                'ts': msg['ts']
            }
            enriched_messages.append(enriched_msg)
        
        logger.info(f"Successfully enriched {len(enriched_messages)} messages with usernames")
        return enriched_messages
    
    def send_message(self, channel, text, blocks=None):
        """Send a message to a Slack channel"""
        try:
            logger.info(f"Sending message to channel {channel}")
            response = self.client.chat_postMessage(
                channel=channel,
                text=text,
                blocks=blocks
            )
            logger.info(f"Message sent to {channel}: {response['ts']}")
            return response
        except SlackApiError as e:
            logger.error(f"SlackApiError sending message to {channel}: {e.response['error']}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error sending message to {channel}: {str(e)}", exc_info=True)
            raise
    
    def update_message(self, channel, ts, text, blocks=None):
        """Update an existing message in Slack"""
        try:
            logger.info(f"Updating message {ts} in channel {channel}")
            response = self.client.chat_update(
                channel=channel,
                ts=ts,
                text=text,
                blocks=blocks
            )
            logger.info(f"Message updated in {channel}: {response['ts']}")
            return response
        except SlackApiError as e:
            logger.error(f"SlackApiError updating message {ts} in {channel}: {e.response['error']}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error updating message {ts} in {channel}: {str(e)}", exc_info=True)
            raise
    
    def get_user_info(self, user_id):
        """Get user information from Slack API"""
        try:
            logger.debug(f"Fetching user info for {user_id}")
            response = self.client.users_info(user=user_id)
            user_info = response['user']['profile']
            logger.debug(f"User info retrieved for {user_id}")
            return user_info
        except SlackApiError as e:
            logger.error(f"SlackApiError getting user info for {user_id}: {e.response['error']}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error getting user info for {user_id}: {str(e)}", exc_info=True)
            raise
    
    def get_channel_info(self, channel_id):
        """Get channel information from Slack API"""
        try:
            logger.debug(f"Fetching channel info for {channel_id}")
            response = self.client.conversations_info(channel=channel_id)
            channel_info = response['channel']
            logger.debug(f"Channel info retrieved for {channel_id}")
            return channel_info
        except SlackApiError as e:
            logger.error(f"SlackApiError getting channel info for {channel_id}: {e.response['error']}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error getting channel info for {channel_id}: {str(e)}", exc_info=True)
            raise
    
    def fetch_unread_messages(self, channel_id, user_id):
        """Fetch only unread messages for a specific user in a channel"""
        try:
            logger.info(f"Fetching unread messages for user {user_id} in channel {channel_id}")
            
            # Import the model here to avoid circular imports
            from ..models import UserChannelReadState
            
            # Step 1: Get the user's last read timestamp from our database
            last_read_ts = UserChannelReadState.get_last_read_ts(user_id, channel_id)
            logger.info(f"User's last read timestamp: {last_read_ts}")
            
            # Step 2: Check if user is a member of the channel
            try:
                members_response = self.client.conversations_members(channel=channel_id)
                if user_id not in members_response.get('members', []):
                    logger.warning(f"User {user_id} is not a member of channel {channel_id}")
                    return []
            except SlackApiError as e:
                if e.response['error'] == 'not_in_channel':
                    logger.warning(f"Bot not in channel {channel_id}")
                    return []
                logger.error(f"Error checking channel membership: {e.response['error']}")
                return []
            
            # Step 3: Fetch messages newer than the last read timestamp
            logger.info(f"Fetching messages newer than {last_read_ts}")
            
            messages = []
            cursor = None
            page_count = 0
            newest_ts = None
            
            while True:
                page_count += 1
                logger.debug(f"Fetching unread messages page {page_count}")
                
                response = self.client.conversations_history(
                    channel=channel_id,
                    oldest=str(last_read_ts),  # Only get messages newer than last read
                    cursor=cursor,
                    limit=200
                )
                
                channel_messages = response.get('messages', [])
                logger.debug(f"Retrieved {len(channel_messages)} raw messages on page {page_count}")
                
                if not channel_messages:
                    break
                
                # Filter for valid unread messages
                filtered_count = 0
                for msg in channel_messages:
                    # Skip if message is older than or equal to last read timestamp
                    if float(msg['ts']) <= float(last_read_ts):
                        continue
                    
                    # Apply standard message filtering
                    if self._is_valid_unread_message(msg, user_id):
                        messages.append(msg)
                        filtered_count += 1
                        
                        # Track the newest message timestamp
                        if newest_ts is None or float(msg['ts']) > float(newest_ts):
                            newest_ts = msg['ts']
                
                logger.debug(f"Filtered to {filtered_count} unread messages on page {page_count}")
                
                cursor = response.get('response_metadata', {}).get('next_cursor')
                if not cursor:
                    break
                    
                # Rate limiting protection
                time.sleep(0.5)
            
            # Step 4: Update the user's last read timestamp to the newest message
            # This way, next time they ask for unread, they won't see these messages again
            if newest_ts and messages:
                UserChannelReadState.update_last_read(user_id, channel_id, newest_ts)
                logger.info(f"Updated last read timestamp to {newest_ts} for user {user_id}")
            
            # Sort messages by timestamp (oldest first)
            messages.sort(key=lambda x: float(x['ts']))
            
            logger.info(f"Found {len(messages)} truly unread messages for user {user_id} in {channel_id}")
            return messages
            
        except SlackApiError as e:
            logger.error(f"SlackApiError fetching unread messages from {channel_id}: {e.response['error']}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error fetching unread messages from {channel_id}: {str(e)}", exc_info=True)
            return []
    
    def _is_valid_unread_message(self, msg, user_id):
        """Determine if a message is a valid unread message"""
        # Basic message validation
        if (msg.get('type') != 'message' or 
            msg.get('bot_id') or 
            not msg.get('user') or
            msg.get('subtype')):
            return False
        
        # Don't include the user's own messages
        if msg.get('user') == user_id:
            return False
        
        # Don't include very old messages (safety check - older than 24 hours)
        msg_time = datetime.fromtimestamp(float(msg['ts']))
        cutoff_time = datetime.now() - timedelta(hours=24)
        
        if msg_time < cutoff_time:
            return False
        
        return True 