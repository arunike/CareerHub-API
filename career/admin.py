from django.contrib import admin
from .models import Company, Application, Offer, Document, GoogleSheetSyncConfig, GoogleSheetSyncRow, Task

admin.site.register(Company)
admin.site.register(Application)
admin.site.register(Offer)
admin.site.register(Document)
admin.site.register(GoogleSheetSyncConfig)
admin.site.register(GoogleSheetSyncRow)
admin.site.register(Task)
