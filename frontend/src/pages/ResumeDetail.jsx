import { Link, useParams } from "react-router-dom";
import Alert from "../components/Alert";
import { CategoryChart } from "../components/Charts";
import Disclaimer from "../components/Disclaimer";
import IssueList from "../components/IssueList";
import ScoreRing from "../components/ScoreRing";
import Section from "../components/Section";
import SkillChips from "../components/SkillChips";
import Spinner from "../components/Spinner";
import { useAsync } from "../hooks/useAsync";
import { resumeApi } from "../services/api";
import { groupBy } from "../utils/format";
import PageHeader from "../components/PageHeader";

const Row = ({ label, value }) => (
  <div className="flex gap-3 text-sm py-1"><dt className="w-24 text-slate2 shrink-0">{label}</dt><dd>{value || "Not detected"}</dd></div>
);

export default function ResumeDetail() {
  const { id } = useParams();
  const { data: r, loading, error } = useAsync(() => resumeApi.get(id), [id]);
  if (loading) return <Spinner label="Loading resume…" />;
  if (error) return <Alert tone="error">{error}</Alert>;

  const pi = r.personal_information;
  const byCat = groupBy(r.skills, "category");
  const chart = Object.entries(byCat).map(([category, s]) => ({ category, count: s.length }));
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <PageHeader eyebrow="Resume details" title={pi.name || r.original_filename} actions={<Link to={`/job-analysis?resume=${r.id}`} className="btn-primary">Match with a job</Link>}>
          {r.original_filename} · {r.file_type.toUpperCase()} · {r.page_count} page(s) · {r.word_count} words
        </PageHeader>
      </div>
      <Disclaimer>Details below were extracted automatically and may contain errors. Please verify them against your resume.</Disclaimer>

      <div className="grid md:grid-cols-3 gap-6">
        <Section title="Contact">
          <dl>
            <Row label="Name" value={pi.name} /><Row label="Email" value={pi.email} /><Row label="Phone" value={pi.phone} />
            <Row label="Location" value={pi.location} /><Row label="GitHub" value={pi.github} /><Row label="LinkedIn" value={pi.linkedin} />
            {Object.entries(pi.links || {}).filter(([key]) => !["github", "linkedin"].includes(key)).map(([key, value]) => <Row key={key} label={key} value={value} />)}
          </dl>
        </Section>
        <Section title="Resume quality" hint="Rule-based checklist, not an ATS prediction">
          <div className="flex justify-center"><ScoreRing value={r.quality_score} label="Quality score" /></div>
        </Section>
        <Section title="Sections detected">
          <SkillChips variant="plain" skills={r.sections_detected} empty="No standard headings found" />
          <p className="text-xs text-slate2 mt-3">{r.nlp_stats.tokens} tokens · {r.nlp_stats.sentences} sentences · spaCy model: {r.nlp_stats.model}</p>
        </Section>
      </div>

      <Section title="Quality issues"><IssueList issues={r.quality_issues} /></Section>

      <div className="grid md:grid-cols-3 gap-6">
        <Section title={`Skills (${r.skills.length})`} hint="Hover a skill to see its heuristic confidence" className="md:col-span-2">
          {Object.entries(byCat).map(([cat, list]) => (
            <div key={cat} className="mb-3"><h3 className="text-sm font-medium mb-1.5">{cat}</h3><SkillChips variant="match" skills={list} /></div>
          ))}
          {!r.skills.length && <p className="text-sm text-slate2">No known skills detected.</p>}
        </Section>
        <Section title="By category"><CategoryChart data={chart} /></Section>
      </div>

      {r.summary && <Section title="Summary"><p className="text-sm whitespace-pre-line">{r.summary}</p></Section>}

      <Section title="Education">
        {!r.education.length ? <p className="text-sm text-slate2">None detected</p> : r.education.map((e, i) => (
          <div key={i} className="py-2 border-b border-rule last:border-0 text-sm">
            <p className="font-medium">{e.degree || "Education entry"}{e.field_of_study && e.degree && !e.degree.includes(e.field_of_study) ? ` in ${e.field_of_study}` : ""}</p>
            <p className="text-slate2">{[e.institution, [e.start_year, e.end_year].filter(Boolean).join(" – "), e.grade && `Grade ${e.grade}`].filter(Boolean).join(" · ")}</p>
          </div>
        ))}
      </Section>

      <Section title="Experience">
        {!r.experience.length ? <p className="text-sm text-slate2">None detected</p> : r.experience.map((e, i) => (
          <div key={i} className="py-3 border-b border-rule last:border-0 text-sm">
            <p className="font-medium">{e.title || "Role"} {e.company && <span className="font-normal">at {e.company}</span>}</p>
            <p className="text-slate2">{[e.start_date && `${e.start_date} – ${e.end_date}`, e.duration_months && `${e.duration_months} months`].filter(Boolean).join(" · ")}</p>
            <p className="whitespace-pre-line mt-1">{e.description}</p>
            <div className="mt-2"><SkillChips variant="plain" skills={e.skills} empty="" /></div>
          </div>
        ))}
      </Section>

      <div className="grid md:grid-cols-2 gap-6">
        <Section title="Projects">
          {!r.projects.length ? <p className="text-sm text-slate2">None detected</p> : r.projects.map((p, i) => (
            <div key={i} className="py-3 border-b border-rule last:border-0 text-sm">
              <p className="font-medium">{p.title}</p>
              <p className="whitespace-pre-line mt-1">{p.description}</p>
              <div className="mt-2"><SkillChips variant="plain" skills={p.technologies} empty="" /></div>
            </div>
          ))}
        </Section>
        <div className="space-y-6">
          <Section title="Certifications">
            {!r.certifications.length ? <p className="text-sm text-slate2">None detected</p> : (
              <ul className="text-sm space-y-1">{r.certifications.map((c, i) => <li key={i}>{c.name}{(c.issuer || c.year) && <span className="text-slate2"> — {[c.issuer, c.year].filter(Boolean).join(", ")}</span>}</li>)}</ul>
            )}
          </Section>
          <Section title="Achievements">
            {!r.achievements.length ? <p className="text-sm text-slate2">None detected</p> : <ul className="text-sm list-disc pl-5 space-y-1">{r.achievements.map((a, i) => <li key={i}>{a}</li>)}</ul>}
          </Section>
        </div>
      </div>
    </div>
  );
}
