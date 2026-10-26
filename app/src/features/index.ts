import type { ComponentType } from 'react';
import DictationPage from './dictation/Page';
import DubbingPage from './dubbing/Page';
import VoiceCloningPage from './voice_cloning/Page';
import VoiceDesignPage from './voice_design/Page';

export interface FeatureEntry {
  id: string;
  title: string;
  Page: ComponentType;
}

export const FEATURES: FeatureEntry[] = [
  { id: 'voice_cloning', title: 'Voice cloning', Page: VoiceCloningPage },
  { id: 'voice_design', title: 'Voice design', Page: VoiceDesignPage },
  { id: 'dubbing', title: 'Dubbing', Page: DubbingPage },
  { id: 'dictation', title: 'Dictation', Page: DictationPage },
];
