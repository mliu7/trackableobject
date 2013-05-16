# encoding: utf-8
import datetime
from south.db import db
from south.v2 import SchemaMigration
from django.db import models

class Migration(SchemaMigration):

    def forwards(self, orm):
        
        # Adding model 'AffectedByMerge'
        db.create_table('trackable_object_affectedbymerge', (
            ('id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('merge_event', self.gf('django.db.models.fields.related.ForeignKey')(to=orm['trackable_object.MergeEvent'])),
            ('content_type', self.gf('django.db.models.fields.related.ForeignKey')(to=orm['contenttypes.ContentType'])),
            ('object_id', self.gf('django.db.models.fields.PositiveIntegerField')()),
        ))
        db.send_create_signal('trackable_object', ['AffectedByMerge'])


    def backwards(self, orm):
        
        # Deleting model 'AffectedByMerge'
        db.delete_table('trackable_object_affectedbymerge')


    models = {
        'contenttypes.contenttype': {
            'Meta': {'ordering': "('name',)", 'unique_together': "(('app_label', 'model'),)", 'object_name': 'ContentType', 'db_table': "'django_content_type'"},
            'app_label': ('django.db.models.fields.CharField', [], {'max_length': '100'}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'model': ('django.db.models.fields.CharField', [], {'max_length': '100'}),
            'name': ('django.db.models.fields.CharField', [], {'max_length': '100'})
        },
        'trackable_object.affectedbymerge': {
            'Meta': {'object_name': 'AffectedByMerge'},
            'content_type': ('django.db.models.fields.related.ForeignKey', [], {'to': "orm['contenttypes.ContentType']"}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'merge_event': ('django.db.models.fields.related.ForeignKey', [], {'to': "orm['trackable_object.MergeEvent']"}),
            'object_id': ('django.db.models.fields.PositiveIntegerField', [], {})
        },
        'trackable_object.mergeevent': {
            'Meta': {'object_name': 'MergeEvent'},
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True', 'db_index': 'True'})
        }
    }

    complete_apps = ['trackable_object']
