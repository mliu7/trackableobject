# encoding: utf-8
import datetime
from south.db import db
from south.v2 import SchemaMigration
from django.db import models

class Migration(SchemaMigration):

    def forwards(self, orm):
        
        # Deleting model 'EditLog'
        db.delete_table('trackable_object_editlog')

        # Adding model 'MergeEvent'
        db.create_table('trackable_object_mergeevent', (
            ('id', self.gf('django.db.models.fields.AutoField')(primary_key=True, db_index=True)),
        ))
        db.send_create_signal('trackable_object', ['MergeEvent'])


    def backwards(self, orm):
        
        # Adding model 'EditLog'
        db.create_table('trackable_object_editlog', (
            ('edit_message', self.gf('django.db.models.fields.CharField')(max_length=100, blank=True)),
            ('editted_by', self.gf('django.db.models.fields.related.ForeignKey')(to=orm['auth.User'])),
            ('object_id', self.gf('django.db.models.fields.PositiveIntegerField')()),
            ('edit_time', self.gf('django.db.models.fields.DateTimeField')()),
            ('content_type', self.gf('django.db.models.fields.related.ForeignKey')(to=orm['contenttypes.ContentType'])),
            ('id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
        ))
        db.send_create_signal('trackable_object', ['EditLog'])

        # Deleting model 'MergeEvent'
        db.delete_table('trackable_object_mergeevent')


    models = {
        'trackable_object.mergeevent': {
            'Meta': {'object_name': 'MergeEvent'},
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True', 'db_index': 'True'})
        }
    }

    complete_apps = ['trackable_object']
