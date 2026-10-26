import type { ComponentType } from 'react';
import {
  AudioLines, BookOpen, FileText, FolderOpen, Languages, Layers, LayoutGrid, Library,
  type LucideIcon, MessagesSquare, Mic, Plug, Wand2, Wrench,
} from 'lucide-react';
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
  group: 'Create' | 'Voices' | 'Dub & transcribe' | 'More';
  icon: LucideIcon;
  Page: ComponentType;
}

export const FEATURES: FeatureEntry[] = [
  { id: 'voice_cloning', title: 'Voice cloning', group: 'Create', icon: AudioLines, Page: VoiceCloningPage },
  { id: 'voice_design', title: 'Voice design', group: 'Create', icon: Wand2, Page: VoiceDesignPage },
  { id: 'voices', title: 'Saved voices', group: 'Voices', icon: Library, Page: VoicesPage },
  { id: 'gallery', title: 'Gallery', group: 'Voices', icon: LayoutGrid, Page: GalleryPage },
  { id: 'stories', title: 'Stories', group: 'Create', icon: MessagesSquare, Page: StoriesPage },
  { id: 'audiobook', title: 'Audiobook', group: 'Create', icon: BookOpen, Page: AudiobookPage },
  { id: 'dubbing', title: 'Dubbing', group: 'Dub & transcribe', icon: Languages, Page: DubbingPage },
  { id: 'batch', title: 'Batch dub', group: 'Dub & transcribe', icon: Layers, Page: BatchPage },
  { id: 'dictation', title: 'Dictation', group: 'Dub & transcribe', icon: Mic, Page: DictationPage },
  { id: 'transcription', title: 'Transcribe', group: 'Dub & transcribe', icon: FileText, Page: TranscriptionPage },
  { id: 'tools', title: 'Tools', group: 'More', icon: Wrench, Page: ToolsPage },
  { id: 'integrations', title: 'Integrations', group: 'More', icon: Plug, Page: IntegrationsPage },
  { id: 'projects', title: 'Projects', group: 'More', icon: FolderOpen, Page: ProjectsPage },
];
