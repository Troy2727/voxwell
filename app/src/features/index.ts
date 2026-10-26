import type { ComponentType } from 'react';
import AudiobookPage from './audiobook/Page';
import BatchPage from './batch/Page';
import DictationPage from './dictation/Page';
import DubbingPage from './dubbing/Page';
import GalleryPage from './gallery/Page';
import IntegrationsPage from './integrations/Page';
import ProjectsPage from './projects/Page';
import StoriesPage from './stories/Page';
import ToolsPage from './tools/Page';
import TranscriptionPage from './transcription/Page';
import VoiceCloningPage from './voice_cloning/Page';
import VoiceDesignPage from './voice_design/Page';
import VoicesPage from './voices/Page';

export interface FeatureEntry {
  id: string;
  title: string;
  Page: ComponentType;
}

export const FEATURES: FeatureEntry[] = [
  { id: 'voice_cloning', title: 'Voice cloning', Page: VoiceCloningPage },
  { id: 'voice_design', title: 'Voice design', Page: VoiceDesignPage },
  { id: 'voices', title: 'Saved voices', Page: VoicesPage },
  { id: 'gallery', title: 'Gallery', Page: GalleryPage },
  { id: 'stories', title: 'Stories', Page: StoriesPage },
  { id: 'audiobook', title: 'Audiobook', Page: AudiobookPage },
  { id: 'dubbing', title: 'Dubbing', Page: DubbingPage },
  { id: 'batch', title: 'Batch dub', Page: BatchPage },
  { id: 'dictation', title: 'Dictation', Page: DictationPage },
  { id: 'transcription', title: 'Transcribe', Page: TranscriptionPage },
  { id: 'tools', title: 'Tools', Page: ToolsPage },
  { id: 'integrations', title: 'Integrations', Page: IntegrationsPage },
  { id: 'projects', title: 'Projects', Page: ProjectsPage },
];
