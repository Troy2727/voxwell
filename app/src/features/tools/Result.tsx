import { apiUrl } from '../../api';
import { AudioResult } from '@/components/audio-result';

export const Result = ({ url, name }: { url: string; name: string }) => <AudioResult src={apiUrl(url)} download={name} />;
