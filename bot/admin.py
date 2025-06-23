from django.contrib import admin
from .models import UserChannelReadState

@admin.register(UserChannelReadState)
class UserChannelReadStateAdmin(admin.ModelAdmin):
    list_display = ('user_id', 'channel_id', 'last_read_ts', 'updated_at')
    list_filter = ('updated_at', 'created_at')
    search_fields = ('user_id', 'channel_id')
    readonly_fields = ('created_at', 'updated_at')
    ordering = ('-updated_at',)
    
    def get_queryset(self, request):
        return super().get_queryset(request) 