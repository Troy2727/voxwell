import { useEffect, useRef, useState } from 'react';
import { Captions, Download, Languages } from 'lucide-react';
import { api, apiUrl, listVoices, type Voice } from '../../api';
import { ChoiceSelect } from '@/components/choice-select';
import { FileDrop } from '@/components/file-drop';
import { JobProgress } from '@/components/job-progress';
import { ErrorAlert, Field, message, Muted, Page as PageLayout, Section } from '@/components/page';
import { appendSpeakerFields, SpeakerOptions } from '@/components/speaker-options';
import { VoiceSelect } from '@/components/voice-select';
import { Button } from '@/components/ui/button';
import { LANGUAGES } from './languages';

interface JobStatus {
  id: string;
  state: 'queued' | 'running' | 'done' | 'error';
  step: string;
  percent: number;
  error: string | null;
}

const ORIGINAL = 'original';

export default function Page() {
  const [file, setFile] = useState<File | null>(null);
  const [language, setLanguage] = useState('es');
  const [voice, setVoice] = useState(ORIGINAL);
  const [speakers, setSpeakers] = useState(false);
  const [speakerCount, setSpeakerCount] = useState('');
  const [voices, setVoices] = useState<Voice[]>([]);
  const [job, setJob] = useState<JobStatus | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    listVoices().then(setVoices, () => setVoices([]));
    return () => window.clearTimeout(timer.current);
  }, []);

  const poll = (id: string) => {
    api<JobStatus>(`/api/dubbing/jobs/${id}`).then(
      (status) => {
        setJob(status);
        if (status.state === 'queued' || status.state === 'running') {
          timer.current = window.setTimeout(() => poll(id), 1000);
        } else {
          setBusy(false);
        }
      },
      (e) => {
        setError(message(e));
        setBusy(false);
      },
    );
  };

  const start = async () => {
    if (!file) return;
    setError('');
    setJob(null);
    setBusy(true);
    const form = new FormData();
    form.append('file', file);
    form.append('target_language', language);
    form.append('voice', voice);
    appendSpeakerFields(form, speakers, speakerCount);
    try {
      const { id } = await api<{ id: string }>('/api/dubbing/jobs', { method: 'POST', body: form });
      poll(id);
    } catch (e) {
      setError(message(e));
      setBusy(false);
    }
  };

  const failed = job?.state === 'error';

  return (
    <PageLayout title="Dubbing" description="Translate a video into another language, spoken in the original voice or one of yours.">
      <Section title="Video">
        <FileDrop file={file} onFile={setFile} accept="video/*,.mkv" disabled={busy} hint="MP4, MKV, MOV, WebM…" />
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Target language">
            <ChoiceSelect options={LANGUAGES} value={language} onChange={setLanguage} />
          </Field>
          <Field label="Voice">
            <VoiceSelect
              voices={voices}
              value={voice === ORIGINAL ? '' : voice}
              onChange={(id) => setVoice(id || ORIGINAL)}
              defaultLabel="Original speaker"
              defaultDescription="Clone the voice in the video"
            />
          </Field>
        </div>
        <SpeakerOptions
          enabled={speakers}
          onEnabled={setSpeakers}
          count={speakerCount}
          onCount={setSpeakerCount}
          disabled={busy}
          hint="Each speaker keeps their own voice when cloning the original, and the subtitles say who speaks. A saved voice speaks every line."
        />
        {voices.length === 0 && <Muted className="text-xs">No saved voices yet; create one in Voice cloning or Voice design.</Muted>}
        <div>
          <Button disabled={!file || busy} onClick={start}>
            <Languages /> {busy ? 'Dubbing…' : 'Start'}
          </Button>
        </div>
      </Section>

      {job && !failed && job.state !== 'done' && (
        <Section title="Dubbing">
          <JobProgress step={job.step} percent={job.percent} hint="You can leave this page; the dub keeps going and appears in Projects." />
        </Section>
      )}
      <ErrorAlert message={error || (failed ? job?.error ?? 'Failed' : '')} />

      {job?.state === 'done' && (
        <Section title="Dubbed video">
          <video controls src={apiUrl(`/api/dubbing/jobs/${job.id}/video`)} />
          <div className="flex flex-wrap gap-2">
            <Button asChild variant="outline">
              <a href={apiUrl(`/api/dubbing/jobs/${job.id}/video`)} download="dubbed.mp4"><Download /> Download video</a>
            </Button>
            <Button asChild variant="outline">
              <a href={apiUrl(`/api/dubbing/jobs/${job.id}/subtitles`)} download="subtitles.srt"><Captions /> Download subtitles</a>
            </Button>
          </div>
        </Section>
      )}
    </PageLayout>
  );
}
