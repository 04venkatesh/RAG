from django.contrib import admin
from .models import Document, DocumentChunk

@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ('id', 'original_filename', 'user', 'file_type', 'file_size_formatted', 'status', 'created_at')
    list_filter = ('status', 'file_type', 'created_at')
    search_fields = ('original_filename', 'user__username', 'error_message')
    readonly_fields = ('created_at', 'updated_at', 'file_size')

@admin.register(DocumentChunk)
class DocumentChunkAdmin(admin.ModelAdmin):
    list_display = ('id', 'document', 'chunk_index', 'page_number', 'chroma_id', 'created_at')
    list_filter = ('document__file_type', 'created_at')
    search_fields = ('content', 'chroma_id', 'document__original_filename')
    readonly_fields = ('created_at',)
