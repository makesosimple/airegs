"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Upload,
  Trash2,
  Database,
  FileText,
  ArrowLeft,
  CheckCircle,
} from "lucide-react";
import Link from "next/link";
import {
  uploadDocument,
  listDocuments,
  deleteDocument,
  getStats,
  type DocumentInfo,
} from "@/lib/api";

const SOURCES = ["BDDK", "SPK", "TCMB", "Kurum İçi", "Diğer"];
const DOC_TYPES = ["Tebliğ", "Yönetmelik", "Duyuru", "Prosedür", "Diğer"];

export default function AdminPage() {
  const [documents, setDocuments] = useState<DocumentInfo[]>([]);
  const [stats, setStats] = useState<{
    points_count: number;
    status: string;
  } | null>(null);
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState("");

  const [file, setFile] = useState<File | null>(null);
  const [source, setSource] = useState("BDDK");
  const [docType, setDocType] = useState("Tebliğ");
  const [title, setTitle] = useState("");
  const [date, setDate] = useState("");

  const loadData = useCallback(async () => {
    try {
      const [docs, st] = await Promise.all([listDocuments(), getStats()]);
      setDocuments(docs);
      setStats(st);
    } catch {
      setMessage("Veriler yüklenirken hata oluştu.");
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;

    setUploading(true);
    setMessage("");

    try {
      await uploadDocument(
        file,
        source,
        docType,
        title || undefined,
        date || undefined
      );
      setMessage(`"${file.name}" başarıyla yüklendi ve indekslendi.`);
      setFile(null);
      setTitle("");
      setDate("");
      const fileInput = document.getElementById(
        "file-input"
      ) as HTMLInputElement;
      if (fileInput) fileInput.value = "";
      await loadData();
    } catch {
      setMessage("Doküman yüklenirken hata oluştu.");
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async (doc: DocumentInfo) => {
    if (!confirm(`"${doc.title}" silinecek. Emin misiniz?`)) return;

    try {
      await deleteDocument(doc.id);
      setMessage(`"${doc.title}" silindi.`);
      await loadData();
    } catch {
      setMessage("Silme işlemi başarısız.");
    }
  };

  return (
    <div className="flex h-screen flex-col bg-main-bg">
      {/* Header */}
      <header className="flex items-center gap-4 border-b border-border-color px-6 py-3">
        <Link
          href="/"
          className="flex items-center gap-1.5 rounded-lg px-2 py-1 text-sm text-text-muted hover:bg-gray-100"
        >
          <ArrowLeft size={14} />
          Sohbet
        </Link>
        <h1 className="text-base font-medium text-text-primary">
          Doküman Yönetimi
        </h1>
      </header>

      <div className="flex-1 overflow-y-auto p-6">
        <div className="mx-auto max-w-5xl">
          {/* Stats */}
          {stats && (
            <div className="mb-6 grid grid-cols-3 gap-4">
              <div className="rounded-xl border border-border-color bg-input-bg p-4">
                <div className="flex items-center gap-2 text-text-muted">
                  <Database size={14} />
                  <span className="text-xs">Toplam Chunk</span>
                </div>
                <p className="mt-1 text-2xl font-bold text-accent">
                  {stats.points_count}
                </p>
              </div>
              <div className="rounded-xl border border-border-color bg-input-bg p-4">
                <div className="flex items-center gap-2 text-text-muted">
                  <FileText size={14} />
                  <span className="text-xs">Doküman Sayısı</span>
                </div>
                <p className="mt-1 text-2xl font-bold text-text-primary">
                  {documents.length}
                </p>
              </div>
              <div className="rounded-xl border border-border-color bg-input-bg p-4">
                <div className="flex items-center gap-2 text-text-muted">
                  <CheckCircle size={14} />
                  <span className="text-xs">Veritabanı</span>
                </div>
                <p className="mt-1 text-2xl font-bold text-emerald-600">
                  {stats.status === "green" ? "Aktif" : stats.status}
                </p>
              </div>
            </div>
          )}

          {/* Message */}
          {message && (
            <div className="mb-4 rounded-xl border border-accent/30 bg-blue-50 px-4 py-3 text-sm text-accent">
              {message}
            </div>
          )}

          {/* Upload form */}
          <div className="mb-6 rounded-xl border border-border-color bg-input-bg p-6">
            <h2 className="mb-4 flex items-center gap-2 text-base font-semibold text-text-primary">
              <Upload size={16} />
              Doküman Yükle
            </h2>
            <form onSubmit={handleUpload} className="flex flex-col gap-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="mb-1 block text-xs text-text-muted">
                    Dosya (PDF, DOCX, HTML, TXT)
                  </label>
                  <input
                    id="file-input"
                    type="file"
                    accept=".pdf,.docx,.html,.htm,.txt"
                    onChange={(e) => setFile(e.target.files?.[0] || null)}
                    className="w-full rounded-lg border border-border-color bg-main-bg px-3 py-2 text-sm text-text-primary file:mr-3 file:rounded-md file:border-0 file:bg-blue-50 file:px-3 file:py-1 file:text-xs file:text-accent"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs text-text-muted">
                    Başlık (opsiyonel)
                  </label>
                  <input
                    type="text"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder="Doküman başlığı"
                    className="w-full rounded-lg border border-border-color bg-main-bg px-3 py-2 text-sm text-text-primary placeholder-text-muted focus:outline-none"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs text-text-muted">
                    Kaynak Kurum
                  </label>
                  <select
                    value={source}
                    onChange={(e) => setSource(e.target.value)}
                    className="w-full rounded-lg border border-border-color bg-main-bg px-3 py-2 text-sm text-text-primary focus:outline-none"
                  >
                    {SOURCES.map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-xs text-text-muted">
                    Doküman Türü
                  </label>
                  <select
                    value={docType}
                    onChange={(e) => setDocType(e.target.value)}
                    className="w-full rounded-lg border border-border-color bg-main-bg px-3 py-2 text-sm text-text-primary focus:outline-none"
                  >
                    {DOC_TYPES.map((t) => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-xs text-text-muted">
                    Tarih (opsiyonel)
                  </label>
                  <input
                    type="date"
                    value={date}
                    onChange={(e) => setDate(e.target.value)}
                    className="w-full rounded-lg border border-border-color bg-main-bg px-3 py-2 text-sm text-text-primary focus:outline-none"
                  />
                </div>
              </div>
              <button
                type="submit"
                disabled={!file || uploading}
                className="flex w-fit items-center gap-2 rounded-lg bg-accent px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-hover disabled:opacity-40"
              >
                <Upload size={14} />
                {uploading ? "Yükleniyor..." : "Yükle ve İndeksle"}
              </button>
            </form>
          </div>

          {/* Document list */}
          <div className="rounded-xl border border-border-color bg-input-bg p-6">
            <h2 className="mb-4 flex items-center gap-2 text-base font-semibold text-text-primary">
              <FileText size={16} />
              Yüklenen Dokümanlar
            </h2>
            {documents.length === 0 ? (
              <p className="text-sm text-text-muted">
                Henüz doküman yüklenmemiş.
              </p>
            ) : (
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-border-color text-text-muted">
                    <th className="pb-3 text-xs font-medium">Başlık</th>
                    <th className="pb-3 text-xs font-medium">Kurum</th>
                    <th className="pb-3 text-xs font-medium">Tür</th>
                    <th className="pb-3 text-xs font-medium">Chunk</th>
                    <th className="pb-3 text-xs font-medium">Durum</th>
                    <th className="pb-3 text-xs font-medium"></th>
                  </tr>
                </thead>
                <tbody>
                  {documents.map((doc) => (
                    <tr
                      key={doc.id}
                      className="border-b border-border-color/50"
                    >
                      <td className="py-3 font-medium text-text-primary">
                        {doc.title}
                      </td>
                      <td className="py-3">
                        <span className="rounded bg-gray-100 px-2 py-0.5 text-xs text-text-secondary">
                          {doc.source}
                        </span>
                      </td>
                      <td className="py-3">
                        <span className="rounded bg-gray-100 px-2 py-0.5 text-xs text-text-secondary">
                          {doc.doc_type}
                        </span>
                      </td>
                      <td className="py-3 text-text-secondary">
                        {doc.chunk_count}
                      </td>
                      <td className="py-3">
                        <span className="rounded bg-emerald-50 px-2 py-0.5 text-xs text-emerald-600">
                          {doc.status}
                        </span>
                      </td>
                      <td className="py-3">
                        <button
                          onClick={() => handleDelete(doc)}
                          className="rounded p-1 text-text-muted transition-colors hover:bg-red-500/20 hover:text-red-400"
                        >
                          <Trash2 size={14} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
