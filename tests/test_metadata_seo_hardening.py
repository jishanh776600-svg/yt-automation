
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from core.models import Base, Job, JobState, RenderOutput, UploadRecord, Topic, ScriptRecord
from engines.seo_engine import SEOEngine
from engines.upload_engine import UploadEngine

class TestMetadataSEOHardening(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        Base.metadata.create_all(self.engine)
        Session = sessionmaker(bind=self.engine)
        self.db = Session()
        self.seo_engine = SEOEngine()
        self.upload_engine = UploadEngine()

    def tearDown(self):
        self.db.close()

    def test_01_description_contains_no_internal_ids(self):
        topic = Topic(
            id='top_secret_999',
            title='The Great Emu War',
            summary='In 1932, Australian soldiers were deployed with machine guns against 20,000 emus.',
            category='History'
        )
        script = ScriptRecord(
            id='scr_abc123',
            topic_id='top_secret_999',
            full_text='In 1932, Australia deployed soldiers against thousands of emus. The birds scattered and outran them. [JOB_ID: job_alpha_456] [RUN_ID: run_998877]'
        )
        metadata = self.seo_engine.generate_metadata(topic, script)
        desc = metadata['description']
        self.assertNotIn('JOB_ID', desc)
        self.assertNotIn('job_alpha_456', desc)
        self.assertNotIn('RUN_ID', desc)
        self.assertNotIn('run_998877', desc)
        self.assertNotIn('top_secret_999', desc)
        self.assertNotIn('scr_abc123', desc)

    def test_02_internal_ids_remain_stored_in_database(self):
        job = Job(id='job_prod_secret_777', state=JobState.READY_TO_UPLOAD.value)
        render = RenderOutput(id='rnd_777', job_id=job.id, video_path='data/renders/test.mp4', duration_sec=23.0, file_size_bytes=1048576)
        self.db.add_all([job, render])
        self.db.commit()
        metadata = {
            'title': 'The Great Emu War Was Actually Real',
            'description': 'In 1932, Australia launched a military operation against thousands of emus in Western Australia.\n\n#History #GreatEmuWar #Australia',
            'tags': []
        }
        slot = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=2)
        self.upload_engine._is_test_mode = MagicMock(return_value=True)
        rec = self.upload_engine.schedule_short(self.db, job, render, metadata, slot)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.job_id, 'job_prod_secret_777')
        self.assertEqual(rec.title, 'The Great Emu War Was Actually Real')
        self.assertNotIn('[JOB_ID:', rec.description)

    def test_03_tags_field_is_empty_for_new_uploads(self):
        topic = Topic(id='top_01', title='The Man from Taured Mystery', summary='A traveler with a passport from a nonexistent country.', category='Mystery')
        script = ScriptRecord(id='scr_01', topic_id='top_01', full_text='A traveler arrived at Tokyo airport in 1954 holding a passport from Taured.')
        metadata = self.seo_engine.generate_metadata(topic, script)
        self.assertIn('tags', metadata)
        self.assertEqual(metadata['tags'], [], 'Tags must be strictly empty for new uploads')

    def test_04_existing_tags_are_untouched(self):
        existing_rec = UploadRecord(
            id='upl_legacy_001',
            job_id='job_legacy_001',
            youtube_video_id='YT_LEGACY_123',
            title='Old Published Short',
            description='Legacy description',
            tags='history,mystery,viral,shorts',
            status='PUBLISHED'
        )
        self.db.add(existing_rec)
        self.db.commit()
        reloaded = self.db.query(UploadRecord).filter_by(id='upl_legacy_001').first()
        self.assertEqual(reloaded.tags, 'history,mystery,viral,shorts', 'Existing published tags must never be erased')

    def test_05_title_is_topic_specific_and_concise(self):
        topic = Topic(id='top_02', title='The Great Emu War', summary='Australia fought emus.', category='History')
        metadata = self.seo_engine.generate_metadata(topic)
        title = metadata['title']
        self.assertLessEqual(len(title), 70)
        self.assertIn('Emu War', title)
        self.assertNotIn('Was Truly Unbelievable Was Truly Unbelievable', title)

    def test_06_description_is_topic_specific(self):
        topic = Topic(
            id='top_03',
            title='The 1814 London Beer Flood',
            summary='A massive vat explosion flooded the streets of St. Giles with over 600,000 liters of fermenting beer.',
            category='History'
        )
        script = ScriptRecord(
            id='scr_03',
            topic_id='top_03',
            full_text='In October 1814, a massive vat explosion in London released a deadly tidal wave of beer through the streets.'
        )
        metadata = self.seo_engine.generate_metadata(topic, script)
        desc = metadata['description']
        self.assertIn('beer', desc.lower())
        self.assertIn('london', desc.lower())
        self.assertNotIn('Explore fascinating, documented stories from American and European history', desc)
        self.assertNotIn('Sources & Verification:', desc)

    def test_07_primary_topic_appears_naturally_early(self):
        topic = Topic(
            id='top_04',
            title='The Lake Peigneur Disaster',
            summary='A drilling mistake punctured a salt mine beneath Lake Peigneur, draining the entire lake.',
            category='History'
        )
        metadata = self.seo_engine.generate_metadata(topic)
        desc = metadata['description']
        first_sentence = desc.split('.')[0].lower()
        self.assertTrue('peigneur' in first_sentence or 'lake' in first_sentence)

    def test_08_hashtags_are_relevant_and_limited(self):
        topic = Topic(
            id='top_05',
            title='The Great Emu War',
            summary='Australia deployed troops against emus in Western Australia.',
            category='History'
        )
        metadata = self.seo_engine.generate_metadata(topic)
        hashtags = metadata['hashtags']
        self.assertGreaterEqual(len(hashtags), 3)
        self.assertLessEqual(len(hashtags), 5)
        self.assertTrue(any('Emu' in tag or 'Australia' in tag or 'History' in tag for tag in hashtags))
        self.assertNotIn('#viral', hashtags)
        self.assertNotIn('#trending', hashtags)
        self.assertNotIn('#fyp', hashtags)

    def test_09_no_keyword_stuffing_in_description(self):
        topic = Topic(
            id='top_06',
            title='The Antikythera Mechanism',
            summary='Divers discovered an ancient astronomical computer off the Greek island of Antikythera.',
            category='Mystery'
        )
        metadata = self.seo_engine.generate_metadata(topic)
        desc = metadata['description']
        self.assertNotIn('history, ancient, computer, mystery, viral, shorts', desc)
        self.assertNotIn('Keywords:', desc)
        self.assertNotIn('Tags:', desc)

    def test_10_metadata_matches_actual_content(self):
        topic = Topic(
            id='top_07',
            title='UV Light Reveals Crocodile Camouflage',
            summary='UV light revealed 125-million-year-old fossil camouflage patterns on an ancient crocodile.',
            category='Science'
        )
        script = ScriptRecord(
            id='scr_07',
            topic_id='top_07',
            full_text='Under ultraviolet light, paleontologists discovered preserved camouflage patterns on a 125-million-year-old crocodile fossil.'
        )
        metadata = self.seo_engine.generate_metadata(topic, script)
        desc = metadata['description']
        title = metadata['title']
        self.assertIn('crocodile', title.lower())
        self.assertIn('crocodile', desc.lower())
        self.assertTrue(any('Science' in h or 'Crocodile' in h or 'Fossils' in h or 'Wildlife' in h for h in metadata['hashtags']))

    def test_11_youtube_upload_payload_contains_no_tags_field(self):
        job = Job(id='job_api_payload_test', state=JobState.READY_TO_UPLOAD.value)
        render = RenderOutput(id='rnd_api', job_id=job.id, video_path='data/renders/test.mp4', duration_sec=23.0, file_size_bytes=1048576)
        self.db.add_all([job, render])
        self.db.commit()
        metadata = {
            'title': 'The War That Lasted Only 38 Minutes',
            'description': 'In 1896, Zanzibar surrendered to Britain in just 38 minutes.\n\n#History #Zanzibar #ShortestWar',
            'tags': ['history', 'zanzibar', 'shorts']
        }
        slot = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=2)
        self.upload_engine._is_test_mode = MagicMock(return_value=False)
        self.upload_engine.validate_media_integrity = MagicMock()
        self.upload_engine.recover_orphaned_upload = MagicMock(return_value=(None, 'NO_ORPHAN'))
        mock_youtube = MagicMock()
        captured_body = {}
        def mock_insert(part, body, media_body):
            nonlocal captured_body
            captured_body = body
            req = MagicMock()
            req.next_chunk.return_value = (None, {'id': 'YT_NEW_API_TEST'})
            req.execute.return_value = {'id': 'YT_NEW_API_TEST'}
            return req
        mock_youtube.videos.return_value.insert = mock_insert
        mock_youtube.videos.return_value.list.return_value.execute.return_value = {
            'items': [{
                'id': 'YT_NEW_API_TEST',
                'status': {'privacyStatus': 'private', 'publishAt': slot.strftime('%Y-%m-%dT%H:%M:%SZ')}
            }]
        }
        with patch('googleapiclient.discovery.build', return_value=mock_youtube), patch('google.oauth2.credentials.Credentials.from_authorized_user_file', return_value=MagicMock()), patch.object(Path, 'exists', return_value=True), patch('googleapiclient.http.MediaFileUpload', return_value=MagicMock()):
            rec = self.upload_engine.schedule_short(self.db, job, render, metadata, slot)
            self.assertIsNotNone(rec)
            self.assertIn('snippet', captured_body)
            self.assertNotIn('tags', captured_body['snippet'], 'YouTube API payload must omit the tags field completely')
            self.assertNotIn('[JOB_ID:', captured_body['snippet']['description'])
            self.assertNotIn('job_api_payload_test', captured_body['snippet']['description'])

if __name__ == '__main__':
    unittest.main()
