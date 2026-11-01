from django.apps import AppConfig

class DocumentsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'documents'

    def ready(self):
        # Import signal handlers so the post_delete hook that purges ChromaDB
        # vectors is registered as soon as the app loads.
        from . import signals  # noqa: F401
