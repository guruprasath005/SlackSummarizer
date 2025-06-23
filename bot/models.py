from django.db import models
from django.utils import timezone

class UserChannelReadState(models.Model):
    """Track the last read timestamp for each user in each channel"""
    user_id = models.CharField(max_length=50, help_text="Slack user ID")
    channel_id = models.CharField(max_length=50, help_text="Slack channel ID") 
    last_read_ts = models.CharField(max_length=20, help_text="Slack timestamp of last read message")
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ('user_id', 'channel_id')
        indexes = [
            models.Index(fields=['user_id', 'channel_id']),
            models.Index(fields=['updated_at']),
        ]
    
    def __str__(self):
        return f"User {self.user_id} in Channel {self.channel_id} - Last read: {self.last_read_ts}"
    
    @classmethod
    def get_last_read_ts(cls, user_id, channel_id):
        """Get the last read timestamp for a user in a channel"""
        try:
            read_state = cls.objects.get(user_id=user_id, channel_id=channel_id)
            return read_state.last_read_ts
        except cls.DoesNotExist:
            # If no record exists, assume they haven't read anything
            # Return a timestamp from 2 hours ago as default
            from datetime import datetime, timedelta
            default_time = datetime.now() - timedelta(hours=2)
            return str(default_time.timestamp())
    
    @classmethod
    def update_last_read(cls, user_id, channel_id, timestamp):
        """Update the last read timestamp for a user in a channel"""
        read_state, created = cls.objects.get_or_create(
            user_id=user_id,
            channel_id=channel_id,
            defaults={'last_read_ts': timestamp}
        )
        if not created:
            read_state.last_read_ts = timestamp
            read_state.save()
        return read_state 