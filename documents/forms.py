from django import forms
from .services.loaders import validate_uploaded_file

class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True

class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if isinstance(data, (list, tuple)):
            result = [single_file_clean(d, initial) for d in data]
        else:
            result = single_file_clean(data, initial)
        return result

class DocumentUploadForm(forms.Form):
    files = MultipleFileField(
        label="Select Document(s)",
        help_text="Supported formats: PDF, DOCX, TXT, CSV, XLSX (Max 20MB per file)",
        widget=MultipleFileInput(attrs={
            'class': 'form-control',
            'id': 'file-input',
            'accept': '.pdf,.docx,.txt,.csv,.xlsx'
        })
    )

    def clean_files(self):
        files = self.files.getlist('files')
        if not files:
            raise forms.ValidationError("Please select at least one file to upload.")
        for f in files:
            validate_uploaded_file(f)
        return files
