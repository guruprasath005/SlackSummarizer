import logging
from datetime import datetime
import google.generativeai as genai
from django.conf import settings

logger = logging.getLogger(__name__)

class GeminiService:
    """Service class for interacting with Google Gemini AI"""
    
    def __init__(self):
        genai.configure(api_key=settings.GEMINI_API_KEY)
        # Updated model name - Google has deprecated 'gemini-pro'
        self.model = genai.GenerativeModel('gemini-1.5-flash')
    
    def summarize_messages(self, messages, channel_name):
        """Summarize Slack channel messages using Gemini AI"""
        try:
            if not messages:
                return self._create_fallback_summary(messages, channel_name)
            
            # Format messages for Gemini
            formatted_messages = self._format_messages_for_ai(messages)
            
            # Create the prompt
            prompt = self._create_summarization_prompt(formatted_messages, channel_name, len(messages))
            
            logger.info(f"Sending {len(messages)} messages to Gemini for summarization")
            
            # Get response from Gemini
            response = self.model.generate_content(prompt)
            
            if response and response.text:
                summary = response.text.strip()
                logger.info("Successfully generated summary from Gemini AI")
                return self._format_summary_response(summary, channel_name, len(messages))
            else:
                logger.warning("Gemini returned empty response")
                return self._create_fallback_summary(messages, channel_name)
                
        except Exception as e:
            logger.error(f"Error generating summary from Gemini: {str(e)}")
            return self._create_fallback_summary(messages, channel_name)
    
    def _format_messages_for_ai(self, messages):
        """Format messages for AI processing"""
        formatted = []
        
        for msg in messages:
            timestamp = msg['timestamp'].strftime("%H:%M")
            username = msg['username']
            text = msg['text']
            
            # Clean up the message text
            if text.strip():
                formatted.append(f"[{timestamp}] @{username}: {text}")
        
        return formatted
    
    def _create_summarization_prompt(self, formatted_messages, channel_name, message_count):
        """Create a comprehensive prompt for message summarization"""
        messages_text = '\n'.join(formatted_messages)
        
        prompt = f"""Please analyze and summarize the following Slack channel conversation from #{channel_name}.

CONVERSATION DATA:
{messages_text}

FORMATTING REQUIREMENTS:
- Use clean, professional formatting
- Use emoji bullet points (🔹) instead of asterisks or dashes
- Organize information in clear sections
- Use bold text for section headers
- Keep it concise and business-appropriate
- No markdown asterisks (*) - use proper Slack formatting

ANALYSIS INSTRUCTIONS:
1. Identify the main topics or themes discussed
2. Highlight any decisions made or action items
3. Note any questions asked and their resolution status
4. Identify the most active participants
5. Flag any urgent or time-sensitive matters
6. Assess the overall tone and productivity of the discussion

RESPONSE FORMAT:
Use this exact structure:

**📋 Key Topics Discussed:**
🔹 [Topic 1 with brief description]
🔹 [Topic 2 with brief description]

**⚡ Important Decisions & Actions:**
🔹 [Decision or action item 1]
🔹 [Decision or action item 2]

**❓ Questions & Status:**
🔹 [Question and whether it was answered]

**👥 Most Active Contributors:**
🔹 [Username and their main contributions]

**🚨 Urgent Items:** (only if applicable)
🔹 [Any time-sensitive or urgent matters]

CONTEXT:
- Channel: #{channel_name}
- Messages analyzed: {message_count}
- Time period: Last 24 hours

Generate a professional, executive-style summary that would be valuable for team leads or managers."""
        
        return prompt
    
    def _format_summary_response(self, summary, channel_name, message_count):
        """Format the final summary response for Slack"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        return f"""📊 **Summary Report for #{channel_name}**

{summary}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📈 **Report Details:** {message_count} messages analyzed | Last 24 hours
🤖 **AI Analysis:** Generated on {timestamp}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""
    
    def _create_fallback_summary(self, messages, channel_name):
        """Create a basic summary when AI fails"""
        if not messages:
            return f"""📊 **Summary Report for #{channel_name}**

**📋 Channel Status:**
🔹 No messages found in the last 24 hours
🔹 Channel appears to be inactive during this period

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📈 **Report Details:** No recent activity to analyze
🤖 **AI Analysis:** Generated on {datetime.now().strftime("%Y-%m-%d %H:%M")}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""
        
        # Create basic stats
        users = set(msg['username'] for msg in messages)
        message_count = len(messages)
        
        return f"""📊 **Summary Report for #{channel_name}**

**📋 Activity Overview:**
🔹 {message_count} messages exchanged in the last 24 hours
🔹 {len(users)} team members participated
🔹 Contributors: {', '.join(list(users)[:5])}{'...' if len(users) > 5 else ''}

**📝 Recent Activity:**
{self._get_recent_messages_summary(messages[:3])}

**⚠️ Note:** AI summarization temporarily unavailable - showing basic analytics

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📈 **Report Details:** {message_count} messages analyzed | Last 24 hours
🤖 **AI Analysis:** Generated on {datetime.now().strftime("%Y-%m-%d %H:%M")}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""
    
    def _get_recent_messages_summary(self, recent_messages):
        """Get a simple summary of recent messages"""
        if not recent_messages:
            return "🔹 No recent messages to display"
        
        summary_lines = []
        for msg in recent_messages[-3:]:  # Last 3 messages
            time_str = msg['timestamp'].strftime("%H:%M")
            username = msg['username']
            text = msg['text'][:50] + ('...' if len(msg['text']) > 50 else '')
            summary_lines.append(f"🔹 [{time_str}] @{username}: {text}")
        
        return '\n'.join(summary_lines)
    
    def generate_response(self, prompt, context=None):
        """Generate a response using Gemini AI"""
        try:
            # Prepare the full prompt with context if provided
            full_prompt = prompt
            if context:
                full_prompt = f"Context: {context}\n\nUser: {prompt}"
            
            response = self.model.generate_content(full_prompt)
            logger.info("Generated response from Gemini AI")
            return response.text
        except Exception as e:
            logger.error(f"Error generating response from Gemini: {str(e)}")
            raise
    
    def generate_summary(self, text, max_length=100):
        """Generate a summary of the given text"""
        try:
            prompt = f"Please provide a concise summary of the following text (max {max_length} words):\n\n{text}"
            response = self.model.generate_content(prompt)
            logger.info("Generated summary from Gemini AI")
            return response.text
        except Exception as e:
            logger.error(f"Error generating summary: {str(e)}")
            raise
    
    def answer_question(self, question, context=None):
        """Answer a specific question with optional context"""
        try:
            prompt = f"Question: {question}"
            if context:
                prompt = f"Context: {context}\n\n{prompt}"
            
            response = self.model.generate_content(prompt)
            logger.info("Generated answer from Gemini AI")
            return response.text
        except Exception as e:
            logger.error(f"Error answering question: {str(e)}")
            raise
    
    def summarize_unread_messages(self, messages, channel_name, user_name):
        """Summarize only unread Slack channel messages for a specific user"""
        try:
            if not messages:
                return self._create_unread_fallback_summary(messages, channel_name, user_name)
            
            # Format messages for Gemini
            formatted_messages = self._format_messages_for_ai(messages)
            
            # Create the unread-specific prompt
            prompt = self._create_unread_summarization_prompt(formatted_messages, channel_name, len(messages), user_name)
            
            logger.info(f"Sending {len(messages)} unread messages to Gemini for summarization")
            
            # Get response from Gemini
            response = self.model.generate_content(prompt)
            
            if response and response.text:
                summary = response.text.strip()
                logger.info("Successfully generated unread summary from Gemini AI")
                return self._format_unread_summary_response(summary, channel_name, len(messages), user_name)
            else:
                logger.warning("Gemini returned empty response for unread summary")
                return self._create_unread_fallback_summary(messages, channel_name, user_name)
                
        except Exception as e:
            logger.error(f"Error generating unread summary from Gemini: {str(e)}")
            return self._create_unread_fallback_summary(messages, channel_name, user_name)

    def _create_unread_summarization_prompt(self, formatted_messages, channel_name, message_count, user_name):
        """Create a prompt specifically for unread message summarization"""
        messages_text = '\n'.join(formatted_messages)
        
        prompt = f"""Please analyze and summarize the following UNREAD messages from #{channel_name} for @{user_name}.

UNREAD CONVERSATION DATA:
{messages_text}

FORMATTING REQUIREMENTS:
- Use clean, professional formatting
- Use emoji bullet points (🔹) instead of asterisks or dashes
- Organize information in clear sections
- Use bold text for section headers
- Keep it concise and actionable for someone catching up
- No markdown asterisks (*) - use proper Slack formatting
- Focus on what the user missed while away

ANALYSIS INSTRUCTIONS:
1. Identify the main topics or themes in the unread messages
2. Highlight any mentions of the user (@{user_name}) or responses to their messages
3. Note any decisions made or action items that might affect the user
4. Identify any questions that need the user's attention
5. Flag any urgent or time-sensitive matters
6. Summarize the current state of ongoing discussions

RESPONSE FORMAT:
Use this exact structure:

**📬 Unread Messages Summary for #{channel_name}**

**📋 What You Missed:**
🔹 [Key topic or discussion point 1]
🔹 [Key topic or discussion point 2]

**👤 Mentions & Responses:**
🔹 [Any mentions of @{user_name} or relevant responses]

**⚡ Action Items & Decisions:**
🔹 [Decisions or actions that might affect you]

**❓ Questions Needing Attention:**
🔹 [Questions directed at you or requiring your input]

**🚨 Urgent Items:** (only if applicable)
🔹 [Any time-sensitive matters requiring immediate attention]

**💬 Current Discussion Status:**
🔹 [Brief summary of where conversations currently stand]

CONTEXT:
- Channel: #{channel_name}
- Unread messages: {message_count}
- User: @{user_name}
- Time period: Recent activity since you were last active

Generate a personalized catch-up summary that helps @{user_name} quickly understand what they missed and what needs their attention."""
        
        return prompt

    def _format_unread_summary_response(self, summary, channel_name, message_count, user_name):
        """Format the final unread summary response for Slack"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        return f"""{summary}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📈 **Catch-up Report:** {message_count} unread messages analyzed
👤 **Personalized for:** @{user_name}
🤖 **AI Analysis:** Generated on {timestamp}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""

    def _create_unread_fallback_summary(self, messages, channel_name, user_name):
        """Create a basic unread summary when AI fails"""
        if not messages:
            return f"""📬 **Unread Messages Summary for #{channel_name}**

**📋 Current Status:**
🔹 No unread messages found in the last 2 hours
🔹 You're all caught up with recent activity!

**💡 Tip:** If you expect unread messages, they might be older than 2 hours or you may have already seen them.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📈 **Catch-up Report:** No unread messages to analyze
👤 **Personalized for:** @{user_name}
🤖 **AI Analysis:** Generated on {datetime.now().strftime("%Y-%m-%d %H:%M")}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""
        
        # Create basic stats
        users = set(msg['username'] for msg in messages if hasattr(msg, 'get') and msg.get('username'))
        message_count = len(messages)
        
        return f"""📬 **Unread Messages Summary for #{channel_name}**

**📋 What You Missed:**
🔹 {message_count} new messages since you were last active
🔹 {len(users)} team members were active
🔹 Contributors: {', '.join(list(users)[:5])}{'...' if len(users) > 5 else ''}

**📝 Recent Activity:**
{self._get_recent_messages_summary(messages[:3])}

**⚠️ Note:** AI summarization temporarily unavailable - showing basic unread activity

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📈 **Catch-up Report:** {message_count} unread messages analyzed
👤 **Personalized for:** @{user_name}
🤖 **AI Analysis:** Generated on {datetime.now().strftime("%Y-%m-%d %H:%M")}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━""" 