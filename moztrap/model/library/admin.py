"""
Admin config for library models.

"""
from django.contrib import admin

from ..mtadmin import MTModelAdmin, MTTabularInline, MTStackedInline
from . import models



class CaseVersionInline(MTStackedInline):
    model = models.CaseVersion
    extra = 0
    fieldsets = [
        (
            None, {
                "fields": [
                    "productversion",
                    ("name", "status"),
                    "exists",
                    "description",
                    ]
                }
            )
        ]



class CaseAttachmentInline(MTTabularInline):
    model = models.CaseAttachment
    extra = 0



class CaseStepInline(MTTabularInline):
    model = models.CaseStep
    extra = 0



class CaseTagInline(admin.TabularInline):
    model = models.CaseVersion.tags.through
    raw_id_fields = ["tag"]
    extra = 0


class SuiteCaseInline(MTTabularInline):
    model = models.SuiteCase
    extra = 0



class CaseVersionAdmin(MTModelAdmin):
    list_display = ["__unicode__", "productversion", "deleted_on", "deleted_by"]
    list_filter = ["envs_narrowed", "productversion"]
    inlines = [CaseStepInline, CaseAttachmentInline, CaseTagInline]
    fieldsets = [
        (
            None, {
                "fields": [
                    "productversion",
                    ("case", "name", "status"),
                    "description",
                    "envs_narrowed",
                    ]
                }
            )
        ]
    raw_id_fields = ["case", "tags", "productversion"]
    actions = ["remove_env_narrowing", "fix_environments"]


    def remove_env_narrowing(self, request, queryset):
        for row in queryset:
            row.remove_env_narrowing()
    remove_env_narrowing.short_description = "Remove environment narrowing"

    def fix_environments(self, request, queryset):
        for row in queryset:
            row.fix_environments()
    fix_environments.short_description = "Fix envs on un-narrowed"


class CaseAdmin(MTModelAdmin):
    list_display = ["__unicode__", "product", "deleted_on", "deleted_by"]
    list_filter = ["product", "deleted_on", "suites"]



admin.site.register(models.Suite, MTModelAdmin)
admin.site.register(
    models.Case, CaseAdmin, inlines=[CaseVersionInline, SuiteCaseInline])
admin.site.register(models.CaseVersion, CaseVersionAdmin)
